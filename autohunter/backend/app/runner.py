"""Фоновые циклы: опрос источников (независимо и параллельно), пересчёт, очистка. Состояние — в БД."""
import asyncio
import logging
import random
import time

from sqlalchemy import select

from .config import Settings
from .db import Database
from .models import Listing, SourceState
from .notifier import Notifier
from .pipeline import Pipeline
from .sources.base import FetchContext, SourceAdapter, SourceNotConfigured
from .timeutil import utcnow

log = logging.getLogger("autohunter.runner")


class SourceRunner:
    def __init__(self, adapter: SourceAdapter, db: Database, pipeline: Pipeline, notifier: Notifier,
                 settings: Settings):
        self.adapter, self.db, self.pipeline, self.notifier, self.settings = adapter, db, pipeline, notifier, settings
        self.known_ids: set[str] = set()
        self._loaded = False

    async def _state(self, s) -> SourceState:
        st = await s.get(SourceState, self.adapter.name)
        if st is None:
            st = SourceState(source=self.adapter.name, enabled=True)
            s.add(st)
            await s.flush()
        return st

    async def run_once(self) -> dict:
        """Один цикл опроса. Исключения фиксируются в состоянии источника и пробрасываются."""
        name = self.adapter.name
        async with self.db.session() as s:
            st = await self._state(s)
            cursor = dict(st.cursor or {})
            first_run = st.last_success_at is None
            st.last_attempt_at = utcnow()
            await s.commit()
            if not self._loaded:
                rows = await s.execute(select(Listing.source_id).where(Listing.source == name))
                self.known_ids = {r[0] for r in rows}
                self._loaded = True
        t0 = time.monotonic()
        try:
            result = await self.adapter.fetch(FetchContext(cursor=cursor, known_ids=self.known_ids))
            async with self.db.session() as s:
                res = await self.pipeline.ingest(s, result.items, backfill=first_run)
                st = await self._state(s)
                st.cursor = result.cursor
                st.last_success_at = utcnow()
                st.consecutive_failures = 0
                st.last_error = None
                st.processed_total += res.processed
                st.new_total += res.new
                await s.commit()
            self.known_ids.update(r.source_id for r in result.items)
            await self._notify(res)
            log.info("%s: %d обработано, %d новых, %d изменений цены, %d дублей, %d отклонено (%.2fs)", name,
                     res.processed, res.new, res.price_changes, res.duplicates, res.rejected, time.monotonic() - t0)
            return {"new": res.new, "processed": res.processed}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            async with self.db.session() as s:
                st = await self._state(s)
                st.consecutive_failures += 1
                st.error_total += 1
                st.last_error = f"{type(e).__name__}: {e}"[:1000]
                st.last_error_at = utcnow()
                await s.commit()
            raise

    async def _notify(self, res) -> None:
        if not res.new_ids and not res.changed_ids:
            return
        async with self.db.session() as s:
            ids = list(dict.fromkeys(res.new_ids + res.changed_ids))
            for l in (await s.execute(select(Listing).where(Listing.id.in_(ids)))).scalars():
                try:
                    await self.notifier.maybe_notify(s, l, price_changed=l.id in res.changed_ids)
                except Exception:
                    log.exception("ошибка уведомления для листинга %s", l.id)

    async def loop(self, stop: asyncio.Event) -> None:
        s_ = self.settings
        failures = 0
        while not stop.is_set():
            try:
                await self.run_once()
                failures = 0
                delay = s_.poll_interval_seconds + random.uniform(0, s_.poll_jitter_seconds)
            except SourceNotConfigured as e:
                log.warning("%s: %s — источник приостановлен", self.adapter.name, e)
                delay = 600
            except asyncio.CancelledError:
                raise
            except Exception as e:
                failures += 1
                delay = min(s_.max_backoff_seconds, s_.poll_interval_seconds * 2 ** min(failures, 6))
                delay *= 0.8 + 0.4 * random.random()
                log.error("%s: ошибка (%s: %s), подряд %d, следующая попытка через %.0fс", self.adapter.name,
                          type(e).__name__, e, failures, delay)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


async def maintenance_loop(db: Database, pipeline: Pipeline, settings: Settings, stop: asyncio.Event) -> None:
    interval = settings.revaluation_interval_minutes * 60
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except asyncio.TimeoutError:
            pass
        try:
            async with db.session() as s:
                off = await pipeline.deactivate_stale(s, settings.listing_ttl_hours)
                n = await pipeline.revalue_active(s, limit=1000)
                log.info("обслуживание: пересчитано %d, деактивировано %d", n, off)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("ошибка обслуживания")

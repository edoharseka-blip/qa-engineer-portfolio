"""Конвейер обработки: валидация/нормализация → дубли → сохранение → история цены → оценка → рейтинг.
Вся пачка от источника обрабатывается одной транзакцией; повторно приходящие неизменные объявления
только «касаются» last_seen_at (без пересчёта)."""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .dedupe import is_duplicate
from .models import Listing, PriceHistory
from .normalize import Normalized, ValidationError, normalize
from .schemas import RawListing
from .scoring import ScoringConfig, compute_score, liquidity_estimate
from .store import get_scoring_config, get_valuation_params
from .timeutil import utcnow
from .valuation import ValuationParams, estimate

log = logging.getLogger("autohunter.pipeline")

POOL_LIMIT = 3000


@dataclass
class IngestResult:
    processed: int = 0
    new: int = 0
    updated: int = 0
    price_changes: int = 0
    duplicates: int = 0
    rejected: int = 0
    unchanged: int = 0
    new_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)  # изменилась цена (для событий снижения)


class Pipeline:
    def __init__(self):
        self._pools: dict[tuple, list[Listing]] = {}

    # ---------- пул аналогов ----------
    async def _pool(self, s: AsyncSession, brand: str, model: str | None) -> list[Listing]:
        key = (brand, model)
        if key not in self._pools:
            q = select(Listing).where(Listing.brand == brand, Listing.is_active.is_(True),
                                      Listing.dup_of_id.is_(None))
            if model:
                q = q.where(Listing.model == model)
            q = q.order_by(Listing.last_seen_at.desc()).limit(POOL_LIMIT)
            self._pools[key] = list((await s.execute(q)).scalars())
        return self._pools[key]

    # ---------- основной вход ----------
    async def ingest(self, s: AsyncSession, raws: list[RawListing], backfill: bool = False) -> IngestResult:
        res = IngestResult(processed=len(raws))
        self._pools = {}
        now = utcnow()
        if not raws:
            return res
        by_source: dict[str, set[str]] = {}
        for r in raws:
            by_source.setdefault(r.source, set()).add(str(r.source_id))
        existing: dict[tuple[str, str], Listing] = {}
        for src, ids in by_source.items():
            ids_l = list(ids)
            for i in range(0, len(ids_l), 500):
                rows = await s.execute(select(Listing).where(Listing.source == src,
                                                             Listing.source_id.in_(ids_l[i:i + 500])))
                for l in rows.scalars():
                    existing[(l.source, l.source_id)] = l

        cfg = await get_scoring_config(s)
        vparams = await get_valuation_params(s)
        touch_ids: list[int] = []
        to_value: list[Listing] = []
        seen_in_batch: dict[tuple[str, str], Listing] = {}

        for raw in raws:
            key = (raw.source, str(raw.source_id))
            ex = existing.get(key) or seen_in_batch.get(key)
            if raw.extra.get("light"):  # лёгкая запись: только цена известного объявления
                if ex and raw.price and raw.price != ex.price and ex.is_active:
                    self._apply_price(s, ex, raw.price, now)
                    res.price_changes += 1
                    res.changed_ids.append(ex.id)
                    to_value.append(ex)
                elif ex:
                    touch_ids.append(ex.id)
                continue
            try:
                n = normalize(raw)
            except ValidationError as e:
                res.rejected += 1
                log.debug("отклонено %s/%s: %s", raw.source, raw.source_id, e)
                continue
            if ex is not None:
                if ex.content_hash == n.content_hash:
                    touch_ids.append(ex.id)
                    res.unchanged += 1
                    continue
                changed_price = n.price != ex.price
                self._update_fields(ex, n)
                ex.last_seen_at = now
                ex.is_active = True
                res.updated += 1
                if changed_price:
                    self._apply_price(s, ex, n.price, now)
                    res.price_changes += 1
                    res.changed_ids.append(ex.id)
                to_value.append(ex)
                continue
            listing = await self._insert_new(s, n, now, res, backfill)
            seen_in_batch[key] = listing
            if listing.dup_of_id is None:
                to_value.append(listing)

        if touch_ids:
            for i in range(0, len(touch_ids), 500):
                await s.execute(update(Listing).where(Listing.id.in_(touch_ids[i:i + 500]))
                                .values(last_seen_at=now, is_active=True))
        await s.flush()
        # новые тоже должны быть в пулах для последующих оценок
        for l in to_value:
            await self._value_and_score(s, l, cfg, vparams)
        await s.flush()
        res.new_ids = [l.id for l in seen_in_batch.values() if l.dup_of_id is None]
        return res

    # ---------- вставка/обновление ----------
    @staticmethod
    def _update_fields(l: Listing, n: Normalized) -> None:
        for f in ("title", "description", "url", "generation", "restyling", "year", "engine_volume", "power_hp",
                  "fuel", "transmission", "drive", "body", "mileage", "vin", "trim", "region", "city",
                  "seller_type", "seller_key", "photos", "content_hash"):
            v = getattr(n, f)
            if v is not None:
                setattr(l, f, v)
        l.search_text = f"{l.title} {l.description}".lower()

    @staticmethod
    def _apply_price(s: AsyncSession, l: Listing, new_price: int, now) -> None:
        l.price = new_price
        l.last_seen_at = now
        s.add(PriceHistory(listing_id=l.id, price=new_price, seen_at=now))

    async def _insert_new(self, s: AsyncSession, n: Normalized, now, res: IngestResult, backfill: bool = False) -> Listing:
        dup = await self._find_duplicate(s, n)
        l = Listing(
            source=n.source, source_id=n.source_id, url=n.url, title=n.title, description=n.description,
            search_text=f"{n.title} {n.description}".lower(), brand=n.brand, model=n.model, generation=n.generation,
            restyling=n.restyling, year=n.year, engine_volume=n.engine_volume, power_hp=n.power_hp, fuel=n.fuel,
            transmission=n.transmission, drive=n.drive, body=n.body, mileage=n.mileage, vin=n.vin, trim=n.trim,
            price=n.price, price_initial=n.price, region=n.region, city=n.city, seller_type=n.seller_type,
            seller_key=n.seller_key, photos=n.photos, posted_at=n.posted_at, first_seen_at=now, last_seen_at=now,
            content_hash=n.content_hash, is_demo=n.is_demo, is_backfill=backfill, dup_of_id=dup.id if dup else None, warnings=[],
        )
        s.add(l)
        await s.flush()
        s.add(PriceHistory(listing_id=l.id, price=n.price, seen_at=now))
        if dup:
            dup.repost_count = (dup.repost_count or 0) + 1
            res.duplicates += 1
        else:
            res.new += 1
            if (n.brand, n.model) in self._pools:
                self._pools[(n.brand, n.model)].append(l)
        return l

    async def _find_duplicate(self, s: AsyncSession, n: Normalized) -> Listing | None:
        if n.year is None or n.mileage is None:
            return None
        q = select(Listing).where(
            Listing.brand == n.brand, Listing.model == n.model, Listing.year == n.year,
            Listing.dup_of_id.is_(None), Listing.first_seen_at >= utcnow() - timedelta(days=90),
            ~((Listing.source == n.source) & (Listing.source_id == n.source_id)))
        for cand in (await s.execute(q)).scalars():
            if is_duplicate(n, cand):
                return cand
        return None

    # ---------- оценка ----------
    async def _value_and_score(self, s: AsyncSession, l: Listing, cfg: ScoringConfig,
                               vparams: ValuationParams) -> None:
        pool = await self._pool(s, l.brand, l.model)
        if l not in pool and l.is_active and l.dup_of_id is None:
            pool.append(l)
        v = estimate(l, pool, vparams)
        l.market_price, l.market_low, l.market_high = v.market_price, v.low, v.high
        l.deviation_pct, l.confidence, l.comps_count, l.valuation = v.deviation_pct, v.confidence, v.comps_count, v.to_dict()
        now = utcnow()
        l.valued_at = now
        ages = [((now - (c.posted_at or c.first_seen_at)).total_seconds() / 86400) for c in pool
                if c.first_seen_at and c.model == l.model]
        l.liquidity = liquidity_estimate(catalog.LIQUIDITY_PRIOR.get((l.brand, l.model)), ages)
        hist = await s.execute(select(PriceHistory.price, PriceHistory.seen_at)
                               .where(PriceHistory.listing_id == l.id).order_by(PriceHistory.seen_at))
        history = [(p, t) for p, t in hist.all()]
        sc = compute_score(l, cfg, l.liquidity, history, now)
        l.score, l.score_label, l.score_parts, l.warnings = sc.score, sc.label, sc.parts, sc.warnings

    async def revalue_active(self, s: AsyncSession, limit: int = 5000) -> int:
        """Периодический пересчёт: новые аналоги меняют рынок. Выполняется порциями."""
        self._pools = {}
        cfg = await get_scoring_config(s)
        vparams = await get_valuation_params(s)
        rows = (await s.execute(select(Listing).where(Listing.is_active.is_(True), Listing.dup_of_id.is_(None))
                                .order_by(Listing.valued_at.asc().nullsfirst()).limit(limit))).scalars().all()
        for l in rows:
            await self._value_and_score(s, l, cfg, vparams)
        await s.commit()
        return len(rows)

    async def deactivate_stale(self, s: AsyncSession, ttl_hours: int) -> int:
        cutoff = utcnow() - timedelta(hours=ttl_hours)
        r = await s.execute(update(Listing).where(Listing.is_active.is_(True), Listing.last_seen_at < cutoff)
                            .values(is_active=False))
        await s.commit()
        return r.rowcount or 0

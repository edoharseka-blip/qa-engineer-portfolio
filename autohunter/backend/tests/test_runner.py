import asyncio

from sqlalchemy import func, select

from app.models import Listing, SourceState
from app.notifier import LogTransport, Notifier
from app.pipeline import Pipeline
from app.runner import SourceRunner
from app.sources.base import FetchContext, FetchResult, SourceAdapter, SourceError
from conftest import raw


class Flaky(SourceAdapter):
    name = "test"
    title = "flaky"

    def __init__(self, fail_times):
        self.fail_times, self.calls = fail_times, 0

    def configured(self):
        return True

    async def fetch(self, ctx):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise SourceError("сеть недоступна")
        return FetchResult([raw(f"n{self.calls}")], {"calls": self.calls})


def runner(db, settings, adapter):
    return SourceRunner(adapter, db, Pipeline(), Notifier(settings, LogTransport()), settings)


async def test_failure_recorded_then_recovers(db, settings):
    r = runner(db, settings, Flaky(1))
    try:
        await r.run_once()
        raise AssertionError("ожидалась ошибка")
    except SourceError:
        pass
    async with db.session() as s:
        st = await s.get(SourceState, "test")
        assert st.consecutive_failures == 1 and "сеть недоступна" in st.last_error and st.error_total == 1
        assert st.last_success_at is None
    await r.run_once()
    async with db.session() as s:
        st = await s.get(SourceState, "test")
        assert st.consecutive_failures == 0 and st.last_error is None and st.last_success_at
        assert st.processed_total == 1 and st.new_total == 1 and st.cursor == {"calls": 2}


async def test_loop_survives_errors_and_stops_gracefully(db, settings):
    a = Flaky(3)
    r = runner(db, settings, a)
    stop = asyncio.Event()
    task = asyncio.create_task(r.loop(stop))
    for _ in range(200):
        await asyncio.sleep(0.05)
        async with db.session() as s:
            if (await s.execute(select(func.count(Listing.id)))).scalar_one() >= 2:
                break
    stop.set()
    await asyncio.wait_for(task, timeout=3)  # корректное завершение без cancel
    assert a.calls >= 5
    async with db.session() as s:
        assert (await s.execute(select(func.count(Listing.id)))).scalar_one() >= 2
        assert (await s.get(SourceState, "test")).error_total == 3


async def test_cursor_persists_across_runner_restart(db, settings):
    a = Flaky(0)
    await runner(db, settings, a).run_once()
    seen = {}

    class Spy(Flaky):
        async def fetch(self, ctx):
            seen["cursor"] = ctx.cursor
            seen["known"] = set(ctx.known_ids)
            return FetchResult([], ctx.cursor)

    await runner(db, settings, Spy(0)).run_once()  # «перезапуск»: новый runner читает состояние из БД
    assert seen["cursor"] == {"calls": 1} and seen["known"] == {"n1"}


async def test_independent_sources_dont_block_each_other(db, settings):
    class Slow(Flaky):
        name = "slow"

        async def fetch(self, ctx):
            raise SourceError("down")

    ok, bad = runner(db, settings, Flaky(0)), runner(db, settings, Slow(0))
    res = await asyncio.gather(ok.run_once(), bad.run_once(), return_exceptions=True)
    assert isinstance(res[1], SourceError) and res[0]["new"] == 1

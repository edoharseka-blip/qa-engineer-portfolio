"""Утилиты командной строки: python -m app.cli <команда>"""
import argparse
import asyncio
import json

from .config import get_settings
from .db import Database
from .notifier import LogTransport, Notifier
from .pipeline import Pipeline
from .runner import SourceRunner
from .sources.registry import build_sources
from .store import ensure_default_profiles


async def _seed_demo() -> None:
    s = get_settings()
    db = Database(s.database_url)
    await db.create_all()
    async with db.session() as ses:
        await ensure_default_profiles(ses)
    from .sources.demo import DemoSource
    runner = SourceRunner(DemoSource(s.demo_seed, s.demo_initial_listings, live=False), db, Pipeline(),
                          Notifier(s, LogTransport()), s)
    print(await runner.run_once())
    await db.dispose()


async def _apiad_probe() -> None:
    """Один безопасный запрос к ApiAd, чтобы сверить реальный формат ответа с адаптером."""
    s = get_settings()
    for a in build_sources(s):
        if a.name.startswith("apiad") and a.configured():
            from .sources.base import FetchContext
            r = await a.fetch(FetchContext())
            print(a.name, len(r.items), "объявлений")
            for it in r.items[:3]:
                print(json.dumps(it.model_dump(mode="json"), ensure_ascii=False, indent=2))
            await a.aclose()
            return
    print("ApiAd не настроен: задайте APIAD_API_KEY и SOURCES_ENABLED=apiad_avito,apiad_drom")


def main() -> None:
    p = argparse.ArgumentParser(prog="autohunter")
    p.add_argument("command", choices=["seed-demo", "apiad-probe"])
    cmd = p.parse_args().command
    asyncio.run({"seed-demo": _seed_demo, "apiad-probe": _apiad_probe}[cmd]())


if __name__ == "__main__":
    main()

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from .api.auth import SlidingWindow
from .api.routes import public, router
from .bot import BotService
from .config import Settings, get_settings
from .db import Database
from .notifier import LogTransport, Notifier
from .pipeline import Pipeline
from .runner import SourceRunner, maintenance_loop
from .sources.base import SourceAdapter
from .sources.registry import build_sources
from .store import ensure_default_profiles

log = logging.getLogger("autohunter")


def create_app(settings: Settings | None = None, db: Database | None = None, adapters: list[SourceAdapter] | None = None,
               background: bool = True) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    problems = settings.validate_for_production()
    if problems:
        raise RuntimeError("Небезопасная конфигурация: " + "; ".join(problems))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = _db = db or Database(settings.database_url)
        if _db.engine.dialect.name == "sqlite":
            await _db.create_all()  # для PostgreSQL схему ведёт Alembic (alembic upgrade head)
        async with _db.session() as s:
            await ensure_default_profiles(s)
        app.state.settings = settings
        app.state.adapters = adapters if adapters is not None else build_sources(settings)
        app.state.pipeline = Pipeline()
        app.state.login_limiter = SlidingWindow(10, 300)
        app.state.api_limiter = SlidingWindow(settings.api_rate_limit_per_minute, 60)
        app.state.bot = None
        if settings.telegram_bot_token and background:
            app.state.bot = BotService(settings, _db)
            app.state.notifier = app.state.bot.notifier
        else:
            app.state.notifier = Notifier(settings, LogTransport())
            if not settings.telegram_bot_token:
                log.warning("TELEGRAM_BOT_TOKEN не задан — уведомления выводятся в лог (режим-заглушка)")
        stop = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if background:
            if app.state.bot:
                await app.state.bot.start()
            for a in app.state.adapters:
                if not a.configured():
                    log.warning("источник %s не настроен (%s) — пропущен", a.name, a.status_note)
                    continue
                runner = SourceRunner(a, _db, app.state.pipeline, app.state.notifier, settings)
                tasks.append(asyncio.create_task(runner.loop(stop), name=f"source-{a.name}"))
            tasks.append(asyncio.create_task(maintenance_loop(_db, app.state.pipeline, settings, stop), name="maintenance"))
        try:
            yield
        finally:
            stop.set()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if app.state.bot:
                await app.state.bot.stop()
            for a in app.state.adapters:
                await a.aclose()
            if db is None:
                await _db.dispose()
            log.info("остановлено корректно")

    app = FastAPI(title="AutoHunter", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/") and hasattr(request.app.state, "api_limiter"):
            ip = request.client.host if request.client else "?"
            if not request.app.state.api_limiter.allow(ip):
                return JSONResponse({"detail": "Слишком много запросов"}, status_code=429)
        return await call_next(request)

    app.include_router(public)
    app.include_router(router)

    static = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parents[2] / "frontend" / "dist"))
    if static.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            f = (static / path).resolve()
            if path and f.is_file() and static.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(static / "index.html")
    return app


app = create_app() if os.environ.get("AUTOHUNTER_NO_AUTOAPP") != "1" else None

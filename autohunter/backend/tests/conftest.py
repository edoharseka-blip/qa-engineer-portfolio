import os
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
import pytest_asyncio

os.environ["AUTOHUNTER_NO_AUTOAPP"] = "1"

from app.config import Settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.schemas import RawListing  # noqa: E402
from app.timeutil import utcnow  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", auth_password="pw-test", auth_secret="s" * 32,
                    sources_enabled="demo", telegram_bot_token="", poll_interval_seconds=0.05, poll_jitter_seconds=0,
                    max_backoff_seconds=0.2, demo_initial_listings=120, demo_live=False)


@pytest_asyncio.fixture
async def db(settings):
    d = Database(settings.database_url)
    await d.create_all()
    yield d
    await d.dispose()


@dataclass
class Car:
    """Лёгкий аналог Listing для чистых функций."""
    brand: str = "BMW"
    model: str = "3 Series"
    generation: str | None = "E90"
    year: int | None = 2008
    mileage: int | None = 150_000
    engine_volume: float | None = 2.5
    fuel: str | None = "petrol"
    transmission: str | None = "AT"
    drive: str | None = "RWD"
    region: str | None = "Ростовская область"
    city: str | None = "Ростов-на-Дону"
    price: int = 800_000
    id: int | None = None
    dup_of_id: int | None = None
    vin: str | None = None
    seller_key: str | None = None


_ids = iter(range(1, 10**6))


def car(**kw) -> Car:
    kw.setdefault("id", next(_ids))
    return Car(**kw)


def raw(sid="1", title="BMW 325i E90, 2008", price=800_000, **kw) -> RawListing:
    base = dict(source="test", source_id=sid, url=f"https://example.test/{sid}", title=title,
                description="Пробег 150 000 км, автомат, бензин 2.5", price=price, city="Ростов-на-Дону",
                posted_at=utcnow() - timedelta(seconds=20), seller_type="private")
    base.update(kw)
    return RawListing(**base)

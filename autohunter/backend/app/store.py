"""Мелкие хранилища: KV-настройки, профили поиска, конфиг скоринга."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import catalog
from .models import KV, SearchProfile
from .scoring import ScoringConfig
from .valuation import ValuationParams


async def kv_get(s: AsyncSession, key: str, default=None):
    row = await s.get(KV, key)
    return row.value if row else default


async def kv_set(s: AsyncSession, key: str, value) -> None:
    row = await s.get(KV, key)
    if row:
        row.value = value
    else:
        s.add(KV(key=key, value=value))


async def get_scoring_config(s: AsyncSession) -> ScoringConfig:
    return ScoringConfig.from_dict(await kv_get(s, "scoring"))


async def get_valuation_params(s: AsyncSession) -> ValuationParams:
    d = await kv_get(s, "valuation") or {}
    base = ValuationParams()
    for k, v in d.items():
        if hasattr(base, k):
            setattr(base, k, type(getattr(base, k))(v))
    return base


DEFAULT_REGIONS = ["Ростовская область", "Краснодарский край", *catalog.NEIGHBOR_REGIONS]


async def ensure_default_profiles(s: AsyncSession) -> None:
    exists = (await s.execute(select(SearchProfile.id).limit(1))).first()
    if exists:
        return
    base = {"price_min": 500_000, "price_max": 1_000_000,
            "brands": ["BMW", "Mercedes-Benz", "Audi"], "regions": DEFAULT_REGIONS}
    s.add(SearchProfile(name="Основной поиск", filters=base, notify=True, notify_min_score=70,
                        notify_min_deviation=10.0))
    s.add(SearchProfile(name="Дешевле рынка на 10%+", filters={**base, "deviation_min": 10.0}, notify=False,
                        notify_min_score=0, notify_min_deviation=10.0))
    await s.commit()

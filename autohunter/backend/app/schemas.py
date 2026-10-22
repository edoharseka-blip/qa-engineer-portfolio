"""Pydantic-схемы: сырые данные адаптеров и фильтры объявлений."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RawListing(BaseModel):
    """То, что отдаёт адаптер источника. Поля заполняются тем, что источник реально предоставил."""
    source: str
    source_id: str
    url: str
    title: str = ""
    description: str = ""
    price: int | None = None
    posted_at: datetime | None = None
    city: str | None = None
    region: str | None = None
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    mileage: int | None = None
    engine_volume: float | None = None
    power_hp: int | None = None
    fuel: str | None = None
    transmission: str | None = None
    drive: str | None = None
    body: str | None = None
    trim: str | None = None
    vin: str | None = None
    seller_type: str | None = None
    seller_key: str | None = None
    photos: list[str] = Field(default_factory=list)
    is_demo: bool = False
    extra: dict[str, Any] = Field(default_factory=dict)


class ListingFilter(BaseModel):
    brands: list[str] = []
    models: list[str] = []
    generations: list[str] = []
    year_min: int | None = None
    year_max: int | None = None
    price_min: int | None = None
    price_max: int | None = None
    mileage_min: int | None = None
    mileage_max: int | None = None
    engine_volume_min: float | None = None
    engine_volume_max: float | None = None
    fuels: list[str] = []
    transmissions: list[str] = []
    drives: list[str] = []
    bodies: list[str] = []
    regions: list[str] = []
    cities: list[str] = []
    seller_types: list[str] = []
    sources: list[str] = []
    deviation_min: float | None = None  # % ниже рынка
    score_min: int | None = None
    posted_after: datetime | None = None
    q: str | None = None
    only_favorites: bool = False
    include_hidden: bool = False
    include_duplicates: bool = False
    include_inactive: bool = False

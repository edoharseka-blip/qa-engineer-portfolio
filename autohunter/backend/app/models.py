from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .timeutil import utcnow


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_listing_source"),
        Index("ix_listing_car", "brand", "model", "year"),
        Index("ix_listing_first_seen", "first_seen_at"),
        Index("ix_listing_score", "score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    search_text: Mapped[str] = mapped_column(Text, default="")  # нижний регистр (SQLite lower() не знает кириллицу)

    brand: Mapped[str | None] = mapped_column(String(40), index=True)
    model: Mapped[str | None] = mapped_column(String(60), index=True)
    generation: Mapped[str | None] = mapped_column(String(40))
    restyling: Mapped[bool] = mapped_column(Boolean, default=False)
    year: Mapped[int | None] = mapped_column(Integer)
    engine_volume: Mapped[float | None] = mapped_column(Float)
    power_hp: Mapped[int | None] = mapped_column(Integer)
    fuel: Mapped[str | None] = mapped_column(String(20))
    transmission: Mapped[str | None] = mapped_column(String(20))
    drive: Mapped[str | None] = mapped_column(String(20))
    body: Mapped[str | None] = mapped_column(String(30))
    mileage: Mapped[int | None] = mapped_column(Integer)
    vin: Mapped[str | None] = mapped_column(String(20))
    trim: Mapped[str | None] = mapped_column(String(80))

    price: Mapped[int] = mapped_column(BigInteger)
    price_initial: Mapped[int] = mapped_column(BigInteger)
    region: Mapped[str | None] = mapped_column(String(60), index=True)
    city: Mapped[str | None] = mapped_column(String(80))
    seller_type: Mapped[str | None] = mapped_column(String(20))  # private | dealer
    seller_key: Mapped[str | None] = mapped_column(String(64))
    photos: Mapped[list] = mapped_column(JSON, default=list)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime)  # по данным источника
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime)  # первое уведомление
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    content_hash: Mapped[str | None] = mapped_column(String(40))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_backfill: Mapped[bool] = mapped_column(Boolean, default=False)  # найдено при первом опросе — не для замера задержки

    dup_of_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"), index=True)
    repost_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- оценка ---
    market_price: Mapped[int | None] = mapped_column(BigInteger)
    market_low: Mapped[int | None] = mapped_column(BigInteger)
    market_high: Mapped[int | None] = mapped_column(BigInteger)
    deviation_pct: Mapped[float | None] = mapped_column(Float)  # >0 — ниже рынка
    confidence: Mapped[float | None] = mapped_column(Float)
    comps_count: Mapped[int | None] = mapped_column(Integer)
    valuation: Mapped[dict | None] = mapped_column(JSON)  # объяснение
    valued_at: Mapped[datetime | None] = mapped_column(DateTime)
    score: Mapped[int | None] = mapped_column(Integer)
    score_label: Mapped[str | None] = mapped_column(String(20))
    score_parts: Mapped[dict | None] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    liquidity: Mapped[float | None] = mapped_column(Float)

    history: Mapped[list["PriceHistory"]] = relationship(back_populates="listing", cascade="all, delete-orphan",
                                                         order_by="PriceHistory.seen_at")


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    price: Mapped[int] = mapped_column(BigInteger)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    listing: Mapped[Listing] = relationship(back_populates="history")


class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_min_score: Mapped[int] = mapped_column(Integer, default=70)
    notify_min_deviation: Mapped[float] = mapped_column(Float, default=10.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """Журнал отправок; уникальность гарантирует отсутствие повторных уведомлений."""
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("listing_id", "chat_id", "event_key", name="uq_notification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    event_key: Mapped[str] = mapped_column(String(40))  # new | drop:<price>
    price: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | sent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class SourceState(Base):
    __tablename__ = "source_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    processed_total: Mapped[int] = mapped_column(BigInteger, default=0)
    new_total: Mapped[int] = mapped_column(BigInteger, default=0)
    error_total: Mapped[int] = mapped_column(BigInteger, default=0)
    cursor: Mapped[dict | None] = mapped_column(JSON)


class KV(Base):
    """Небольшие настройки: пауза уведомлений, чаты, веса скоринга."""
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)

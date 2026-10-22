"""Уведомления: правила (профили, пауза, антидубли), форматирование и транспорт-независимая отправка."""
import html
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .filters import matches
from .models import Listing, Notification, SearchProfile
from .schemas import ListingFilter
from .scoring import LABEL_RU
from .store import kv_get
from .timeutil import utcnow

log = logging.getLogger("autohunter.notifier")

SOURCE_RU = {"avito": "Авито", "drom": "Дром", "autoru": "Авто.ру", "demo": "Демо"}
FUEL_RU = {"petrol": "бензин", "diesel": "дизель", "hybrid": "гибрид", "electric": "электро", "gas": "газ"}
TRANS_RU = {"AT": "автомат", "MT": "механика", "AMT": "робот", "CVT": "вариатор"}
DRIVE_RU = {"AWD": "полный", "RWD": "задний", "FWD": "передний"}
SELLER_RU = {"private": "частное лицо", "dealer": "дилер/компания"}


@dataclass
class Button:
    text: str
    url: str | None = None
    callback: str | None = None


class Transport(Protocol):
    async def send(self, chat_id: int, text: str, photo: str | None, buttons: list[list[Button]]) -> None: ...


class LogTransport:
    """Нет токена Telegram: сообщения пишутся в лог и сохраняются в памяти (удобно для демо и тестов)."""
    def __init__(self):
        self.sent: list[tuple[int, str, str | None, list]] = []

    async def send(self, chat_id, text, photo, buttons):
        self.sent.append((chat_id, text, photo, buttons))
        log.info("[telegram-stub → %s]\n%s", chat_id, text)


def rub(v: int | None) -> str:
    return "—" if v is None else f"{v:,}".replace(",", " ") + " ₽"


def source_label(source: str) -> str:
    base = source.replace("apiad_", "")
    return SOURCE_RU.get(base, base) + (" (ApiAd)" if source.startswith("apiad_") else "")


def format_listing(l: Listing, tz: str = "Europe/Moscow", old_price: int | None = None) -> str:
    e = html.escape
    lines = []
    if old_price:
        lines.append(f"📉 <b>Цена снижена:</b> {rub(old_price)} → {rub(l.price)}")
        lines.append("")
    lines.append(f"🚗 <b>{e(l.title)}</b>")
    lines.append("")
    lines.append(f"Цена: <b>{rub(l.price)}</b>")
    if l.market_price and l.deviation_pct is not None:
        lines.append(f"Оценка рынка: {rub(l.market_price)} (достоверность {int((l.confidence or 0) * 100)}%)")
        if l.deviation_pct >= 0:
            lines.append(f"Ниже рынка: <b>{l.deviation_pct:.0f}%</b>")
        else:
            lines.append(f"Выше рынка: {-l.deviation_pct:.0f}%")
    else:
        lines.append("Оценка рынка: недостаточно данных")
    lines.append("")
    if l.mileage is not None:
        lines.append(f"Пробег: {l.mileage:,} км".replace(",", " "))
    eng = " ".join(x for x in (f"{l.engine_volume:.1f}" if l.engine_volume else None, FUEL_RU.get(l.fuel or "", l.fuel)) if x)
    if eng:
        lines.append(f"Двигатель: {eng}")
    if l.transmission:
        lines.append(f"КПП: {TRANS_RU.get(l.transmission, l.transmission)}")
    if l.drive:
        lines.append(f"Привод: {DRIVE_RU.get(l.drive, l.drive)}")
    where = ", ".join(x for x in (l.city, l.region if l.region != l.city else None) if x)
    if where:
        lines.append(f"Город: {e(where)}")
    if l.seller_type:
        lines.append(f"Продавец: {SELLER_RU.get(l.seller_type, l.seller_type)}")
    lines.append("")
    lines.append(f"Оценка AutoHunter: <b>{l.score}/100</b>")
    lines.append(f"Статус: {LABEL_RU.get(l.score_label or '', '—')}")
    for w in (l.warnings or [])[:4]:
        lines.append(e(w))
    lines.append("")
    lines.append(f"Источник: {source_label(l.source)}")
    seen = (l.first_seen_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(tz))).strftime("%H:%M:%S")
    lines.append(f"Обнаружено: {seen}")
    if l.is_demo:
        lines.append("<i>⚠️ демонстрационные данные</i>")
    return "\n".join(lines)


def listing_buttons(l: Listing) -> list[list[Button]]:
    return [
        [Button("🔗 Открыть объявление", url=l.url)],
        [Button("📊 Аналоги", callback=f"comps:{l.id}"),
         Button("⭐ В избранное", callback=f"fav:{l.id}"),
         Button("🙈 Скрыть", callback=f"hide:{l.id}")],
    ]


class Notifier:
    def __init__(self, settings: Settings, transport: Transport):
        self.settings = settings
        self.transport = transport

    async def chat_ids(self, s: AsyncSession) -> list[int]:
        ids = set(self.settings.allowed_chat_ids)
        ids.update(int(x) for x in (await kv_get(s, "telegram_chats", [])) or [])
        if not ids and isinstance(self.transport, LogTransport):
            return [0]  # демо без Telegram: «виртуальный» чат, сообщения видны в логе и в мониторинге
        return sorted(ids)

    async def is_paused(self, s: AsyncSession) -> bool:
        return bool(await kv_get(s, "notifications_paused", False))

    def _fresh(self, l: Listing) -> bool:
        ref = l.posted_at or l.first_seen_at
        return ref >= utcnow() - timedelta(hours=self.settings.notify_max_age_hours)

    async def _matching_profile(self, s: AsyncSession, l: Listing) -> SearchProfile | None:
        profs = (await s.execute(select(SearchProfile).where(SearchProfile.active.is_(True),
                                                             SearchProfile.notify.is_(True)))).scalars()
        for p in profs:
            f = ListingFilter(**p.filters)
            if not matches(l, f):
                continue
            ok_score = l.score is not None and l.score >= p.notify_min_score
            ok_dev = l.deviation_pct is not None and l.deviation_pct >= p.notify_min_deviation
            if ok_score or ok_dev:
                return p
        return None

    async def maybe_notify(self, s: AsyncSession, l: Listing, price_changed: bool = False) -> int:
        """Возвращает число отправленных сообщений. Антидубль: уникальная запись (listing, chat, event)."""
        if l.hidden or l.dup_of_id is not None or not l.is_active or await self.is_paused(s):
            return 0
        chats = await self.chat_ids(s)
        if not chats:
            return 0
        prof = await self._matching_profile(s, l)
        if prof is None:
            return 0
        sent = 0
        for chat in chats:
            prev = (await s.execute(select(Notification).where(
                Notification.listing_id == l.id, Notification.chat_id == chat,
                Notification.status == "sent").order_by(Notification.id.desc()))).scalars().first()
            old_price = None
            if prev is None:
                if not self._fresh(l):
                    continue
                event = "new"
            else:
                drop = (prev.price - l.price) / prev.price * 100 if prev.price else 0
                if not price_changed or drop < self.settings.reprice_notify_pct:
                    continue
                event, old_price = f"drop:{l.price}", prev.price
            claim = Notification(listing_id=l.id, chat_id=chat, event_key=event, price=l.price, status="pending")
            try:
                async with s.begin_nested():
                    s.add(claim)
                    await s.flush()
            except IntegrityError:
                continue
            try:
                await self.transport.send(chat, format_listing(l, self.settings.display_timezone, old_price),
                                          l.photos[0] if l.photos else None, listing_buttons(l))
            except Exception:
                log.exception("не удалось отправить уведомление %s → %s", l.id, chat)
                await s.execute(delete(Notification).where(Notification.id == claim.id))
                await s.commit()
                continue
            claim.status, claim.sent_at = "sent", utcnow()
            if l.notified_at is None:
                l.notified_at = claim.sent_at
            await s.commit()
            sent += 1
        return sent

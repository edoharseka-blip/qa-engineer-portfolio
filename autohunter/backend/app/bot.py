"""Telegram-бот (aiogram 3): транспорт уведомлений, команды, inline-кнопки.
Не проверено на живом Telegram в среде разработки — нужен TELEGRAM_BOT_TOKEN."""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from .config import Settings
from .db import Database
from .models import Listing, SearchProfile
from .notifier import Button, Notifier, format_listing, listing_buttons, rub
from .store import kv_get, kv_set
from .timeutil import utcnow

log = logging.getLogger("autohunter.bot")


def to_markup(buttons: list[list[Button]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b.text, url=b.url) if b.url else InlineKeyboardButton(text=b.text, callback_data=b.callback)
         for b in row] for row in buttons])


class TelegramTransport:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._lock = asyncio.Lock()

    async def send(self, chat_id: int, text: str, photo: str | None, buttons: list[list[Button]]) -> None:
        async with self._lock:  # ~1 сообщение/сек на чат — лимит Telegram
            for attempt in range(3):
                try:
                    if photo and len(text) <= 1000:
                        try:
                            await self.bot.send_photo(chat_id, photo, caption=text, reply_markup=to_markup(buttons))
                            break
                        except Exception:
                            log.warning("фото недоступно, отправляю без него")
                    await self.bot.send_message(chat_id, text, reply_markup=to_markup(buttons),
                                                disable_web_page_preview=True)
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
            await asyncio.sleep(0.05)


SETTING_KEYS = {
    "price_min": int, "price_max": int, "year_min": int, "year_max": int, "mileage_max": int,
    "deviation_min": float,
}


def apply_setting(profile: SearchProfile, key: str, value: str) -> str:
    """Меняет фильтр профиля из команды /set. Возвращает человекочитаемый результат; ValueError при ошибке."""
    f = dict(profile.filters or {})
    key = key.lower()
    if key in SETTING_KEYS:
        if value.lower() in ("none", "-", "нет"):
            f.pop(key, None)
        else:
            f[key] = SETTING_KEYS[key](value.replace(" ", ""))
    elif key in ("brands", "regions", "models", "cities"):
        f[key] = [] if value.lower() in ("none", "-", "все") else [v.strip() for v in value.split(",") if v.strip()]
    elif key == "seller":
        f["seller_types"] = [] if value.lower() in ("any", "все") else [{"private": "private", "частный": "private",
                                                                       "dealer": "dealer", "дилер": "dealer"}[value.lower()]]
    elif key == "min_score":
        profile.notify_min_score = int(value)
    elif key == "min_dev":
        profile.notify_min_deviation = float(value)
    else:
        raise ValueError(f"неизвестный параметр «{key}»")
    profile.filters = f
    return f"{key} = {value}"


def describe_profile(p: SearchProfile) -> str:
    f = p.filters or {}
    rows = [f"<b>{p.name}</b>", f"Цена: {rub(f.get('price_min'))} – {rub(f.get('price_max'))}",
            f"Марки: {', '.join(f.get('brands', [])) or 'все'}",
            f"Регионы: {', '.join(f.get('regions', [])) or 'все'}",
            f"Год: {f.get('year_min', '—')} – {f.get('year_max', '—')}; пробег до: {f.get('mileage_max', '—')}",
            f"Продавец: {', '.join(f.get('seller_types', [])) or 'любой'}",
            f"Уведомлять при рейтинге ≥ {p.notify_min_score} или отклонении ≥ {p.notify_min_deviation:.0f}%"]
    return "\n".join(rows)


def build_dispatcher(settings: Settings, db: Database, notifier: Notifier) -> Dispatcher:
    r = Router()

    async def allowed(chat_id: int) -> bool:
        if chat_id in settings.allowed_chat_ids:
            return True
        async with db.session() as s:
            return chat_id in (await kv_get(s, "telegram_chats", []) or [])

    async def profile(s) -> SearchProfile | None:
        return (await s.execute(select(SearchProfile).order_by(SearchProfile.id).limit(1))).scalars().first()

    @r.message(Command("start"))
    async def start(m: Message, command: CommandObject):
        if not await allowed(m.chat.id):
            if settings.telegram_pairing_code and command.args and command.args.strip() == settings.telegram_pairing_code:
                async with db.session() as s:
                    chats = list(await kv_get(s, "telegram_chats", []) or [])
                    chats.append(m.chat.id)
                    await kv_set(s, "telegram_chats", sorted(set(chats)))
                    await s.commit()
            else:
                return await m.answer("Доступ закрыт. Используйте /start <код>, если он у вас есть.")
        await m.answer("AutoHunter подключён ✅\n/top — лучшие предложения\n/filters — текущие фильтры\n"
                       "/set <параметр> <значение> — изменить фильтр\n/pause, /resume — уведомления\n"
                       "/status — состояние\n/test — тестовое уведомление")

    @r.message(Command("help"))
    async def help_(m: Message):
        if await allowed(m.chat.id):
            await m.answer("Параметры /set: price_min, price_max, year_min, year_max, mileage_max, deviation_min, "
                           "brands, regions, models, seller (private|dealer|any), min_score, min_dev.\n"
                           "Пример: /set price_max 900000 · /set brands BMW,Audi")

    @r.message(Command("pause"))
    async def pause(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            await kv_set(s, "notifications_paused", True)
            await s.commit()
        await m.answer("⏸ Уведомления приостановлены. /resume — возобновить.")

    @r.message(Command("resume"))
    async def resume(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            await kv_set(s, "notifications_paused", False)
            await s.commit()
        await m.answer("▶️ Уведомления возобновлены.")

    @r.message(Command("filters"))
    async def filters_(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            p = await profile(s)
        await m.answer(describe_profile(p) if p else "Профилей нет")

    @r.message(Command("set"))
    async def set_(m: Message, command: CommandObject):
        if not await allowed(m.chat.id):
            return
        parts = (command.args or "").split(maxsplit=1)
        if len(parts) != 2:
            return await m.answer("Формат: /set <параметр> <значение>. См. /help")
        async with db.session() as s:
            p = await profile(s)
            try:
                msg = apply_setting(p, parts[0], parts[1])
            except (ValueError, KeyError) as e:
                return await m.answer(f"Ошибка: {e}")
            await s.commit()
        await m.answer(f"✅ {msg}")

    @r.message(Command("top"))
    async def top(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            rows = (await s.execute(select(Listing).where(
                Listing.is_active.is_(True), Listing.hidden.is_(False), Listing.dup_of_id.is_(None),
                Listing.score.is_not(None)).order_by(Listing.score.desc()).limit(5))).scalars().all()
        if not rows:
            return await m.answer("Пока нет объявлений.")
        for l in rows:
            await m.answer(format_listing(l, settings.display_timezone), reply_markup=to_markup(listing_buttons(l)),
                           disable_web_page_preview=True)

    @r.message(Command("status"))
    async def status(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            paused = await kv_get(s, "notifications_paused", False)
        await m.answer(f"Уведомления: {'⏸ на паузе' if paused else '▶️ включены'}\nИсточники: {settings.sources_enabled}")

    @r.message(Command("test"))
    async def test(m: Message):
        if not await allowed(m.chat.id):
            return
        async with db.session() as s:
            l = (await s.execute(select(Listing).where(Listing.dup_of_id.is_(None)).order_by(Listing.score.desc().nullslast()).limit(1))).scalars().first()
        if l is None:
            return await m.answer("🔔 Тестовое уведомление: база пока пуста, но бот работает.")
        await m.answer("🔔 Тестовое уведомление (пример реального формата):")
        await notifier.transport.send(m.chat.id, format_listing(l, settings.display_timezone), None, listing_buttons(l))

    @r.callback_query(F.data.startswith(("fav:", "hide:", "comps:")))
    async def cb(q: CallbackQuery):
        if not q.message or not await allowed(q.message.chat.id):
            return await q.answer("Нет доступа")
        action, _, sid = q.data.partition(":")
        async with db.session() as s:
            l = await s.get(Listing, int(sid))
            if l is None:
                return await q.answer("Объявление не найдено")
            if action == "fav":
                l.favorite = not l.favorite
                await s.commit()
                return await q.answer("⭐ Добавлено в избранное" if l.favorite else "Убрано из избранного")
            if action == "hide":
                l.hidden = True
                await s.commit()
                return await q.answer("Скрыто")
            ids = [x["id"] for x in (l.valuation or {}).get("sample", []) if x.get("id")][:5]
            comps = (await s.execute(select(Listing).where(Listing.id.in_(ids)))).scalars().all() if ids else []
        await q.answer()
        if not comps:
            return await q.message.answer("Аналогов для сравнения недостаточно.")
        lines = [f"📊 Аналоги для {l.title}:"] + [
            f"• {c.title} — {rub(c.price)}, {c.mileage or '?'} км, {c.city or c.region or ''}\n  {c.url}" for c in comps]
        await q.message.answer("\n".join(lines), disable_web_page_preview=True)

    dp = Dispatcher()
    dp.include_router(r)
    return dp


class BotService:
    """Жизненный цикл: polling в фоне, корректная остановка."""
    def __init__(self, settings: Settings, db: Database):
        self.settings, self.db = settings, db
        self.bot = Bot(settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.transport = TelegramTransport(self.bot)
        self.notifier = Notifier(settings, self.transport)
        self.dp = build_dispatcher(settings, db, self.notifier)
        self.task: asyncio.Task | None = None
        self.started_at = None
        self.last_error: str | None = None

    async def start(self) -> None:
        async def run():
            try:
                self.started_at = utcnow()
                await self.dp.start_polling(self.bot, handle_signals=False)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.last_error = f"{type(e).__name__}: {e}"
                log.exception("polling бота остановлен")
        self.task = asyncio.create_task(run(), name="telegram-bot")

    async def stop(self) -> None:
        try:
            await self.dp.stop_polling()
        except Exception:  # noqa: BLE001
            pass
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.bot.session.close()

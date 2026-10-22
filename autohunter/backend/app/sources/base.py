"""Базовый контракт адаптера источника + HTTP-утилиты (таймауты, повторы с увеличивающимися паузами,
ограничение частоты). Адаптеры независимы: включаются через SOURCES_ENABLED."""
import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from ..schemas import RawListing

log = logging.getLogger("autohunter.sources")


class SourceError(Exception):
    """Ошибка получения данных (сеть, лимиты, ответ неожиданного формата)."""


class SourceNotConfigured(SourceError):
    pass


@dataclass
class FetchContext:
    cursor: dict = field(default_factory=dict)
    known_ids: set[str] = field(default_factory=set)  # source_id уже сохранённых объявлений


@dataclass
class FetchResult:
    items: list[RawListing]
    cursor: dict = field(default_factory=dict)


class RateLimiter:
    """Не чаще одного запроса в min_interval секунд (общий для адаптера)."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._next = max(now, self._next) + self.min_interval


class SourceAdapter(ABC):
    name: str = ""
    title: str = ""
    requires_key: bool = False
    is_demo: bool = False
    status_note: str = ""  # честная пометка: что проверено, что нет

    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    async def fetch(self, ctx: FetchContext) -> FetchResult: ...

    async def aclose(self) -> None:
        return None


async def request_json(client: httpx.AsyncClient, limiter: RateLimiter, method: str, url: str, *,
                       params: dict | None = None, attempts: int = 4, base_delay: float = 1.0,
                       max_delay: float = 30.0) -> dict | list:
    """GET/POST с повторами на сетевые ошибки, 429 и 5xx. 4xx (кроме 429) — не повторяем.
    Уважает Retry-After. Капчи/блокировки не обходим: 403/401 → SourceError."""
    last: Exception | None = None
    for i in range(attempts):
        await limiter.acquire()
        try:
            r = await client.request(method, url, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last = e
            delay = min(max_delay, base_delay * 2 ** i) * (0.8 + 0.4 * random.random())
            log.warning("%s %s: сетевая ошибка (%s), повтор через %.1fс", method, url, type(e).__name__, delay)
            await asyncio.sleep(delay)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            retry_after = r.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else min(max_delay, base_delay * 2 ** i)
            except ValueError:
                delay = min(max_delay, base_delay * 2 ** i)
            last = SourceError(f"HTTP {r.status_code}")
            log.warning("%s %s: HTTP %s, повтор через %.1fс", method, url, r.status_code, delay)
            await asyncio.sleep(min(delay, max_delay))
            continue
        if r.status_code >= 400:
            raise SourceError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise SourceError(f"ответ не JSON: {r.text[:200]}") from e
    raise SourceError(f"исчерпаны попытки: {last}")

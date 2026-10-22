"""Адаптер ApiAd (https://apiad.ru) для Авито и Дрома.

СТАТУС: реализован по публичному описанию (список эндпоинтов и полей на главной странице apiad.ru).
НЕ проверен на реальном ключе: формат `data.params`, цена, лимиты и задержка в документации не указаны.
Парсинг params сделан терпимым к разным формам; после получения ключа сверьте с живым ответом
(`python -m app.cli apiad-probe`). Мы не обходим защиту площадок — данные получаем только через API сервиса.

Стратегия:
  1. `search_transport` (поиск в реальном времени) по запросам из APIAD_QUERIES — быстрый способ увидеть новые URL;
  2. для ещё не известных объявлений — `parse_sync` (до 30 с на запрос, может тарифицироваться!) —
     ограничено APIAD_ENRICH_PER_POLL, чтобы не расходовать лимиты неожиданно."""
import asyncio
import re
from datetime import datetime, timezone

import httpx

from ..schemas import RawListing
from .base import (FetchContext, FetchResult, RateLimiter, SourceAdapter, SourceError, SourceNotConfigured,
                   request_json)

PARAM_KEYS = {
    "year": ("год выпуска", "год", "year"),
    "mileage": ("пробег", "mileage"),
    "engine_volume": ("объём двигателя", "объем двигателя", "объём", "объем", "engine volume"),
    "power_hp": ("мощность", "мощность двигателя", "power"),
    "fuel": ("тип двигателя", "топливо", "тип топлива", "fuel"),
    "transmission": ("коробка передач", "коробка", "кпп", "transmission"),
    "drive": ("привод", "drive"),
    "body": ("тип кузова", "кузов", "body"),
    "brand": ("марка", "brand"),
    "model": ("модель", "model"),
    "trim": ("комплектация", "trim"),
    "vin": ("vin", "vin или номер кузова"),
}


def _num(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d[\d\s ]*(?:[.,]\d+)?", str(v))
    if not m:
        return None
    return float(re.sub(r"\s| ", "", m.group(0)).replace(",", "."))


def flatten_params(params) -> dict[str, str]:
    """params может быть dict, списком {name/title/key, value} или списком строк «Ключ: значение»."""
    out: dict[str, str] = {}
    if isinstance(params, dict):
        for k, v in params.items():
            if isinstance(v, (str, int, float)):
                out[str(k).strip().lower()] = str(v)
    elif isinstance(params, list):
        for it in params:
            if isinstance(it, dict):
                k = it.get("name") or it.get("title") or it.get("key") or it.get("label")
                v = it.get("value") if "value" in it else it.get("val")
                if k is not None and v is not None:
                    out[str(k).strip().lower().rstrip(":")] = str(v)
            elif isinstance(it, str) and ":" in it:
                k, v = it.split(":", 1)
                out[k.strip().lower()] = v.strip()
    return out


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        ts = v / 1000 if v > 1e11 else v
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def raw_from_data(platform: str, src_id: str, data: dict, fallback_price=None, fallback_url=None) -> RawListing:
    p = flatten_params(data.get("params"))

    def pick(field: str):
        for key in PARAM_KEYS[field]:
            if key in p:
                return p[key]
        return None

    price = data.get("price", fallback_price)
    price = int(_num(price)) if _num(price) is not None else None
    images = data.get("images") or []
    photos = [i if isinstance(i, str) else (i.get("url") or i.get("src") or "") for i in images] if isinstance(images, list) else []
    seller_an = data.get("seller_analytics") or {}
    seller_type = None
    if isinstance(seller_an, dict):
        seller_type = seller_an.get("type") or seller_an.get("seller_type")
    seller_key = None
    if isinstance(seller_an, dict):
        seller_key = str(seller_an.get("id") or seller_an.get("seller_id") or "") or None
    year, mileage = _num(pick("year")), _num(pick("mileage"))
    vol, hp = _num(pick("engine_volume")), _num(pick("power_hp"))
    return RawListing(
        source=f"apiad_{platform}", source_id=str(src_id), url=data.get("url") or fallback_url or "",
        title=data.get("title") or "", description=data.get("description") or "", price=price,
        posted_at=_parse_dt(data.get("time_source_created")), city=data.get("city"), region=data.get("region"),
        brand=pick("brand"), model=pick("model"), year=int(year) if year else None,
        mileage=int(mileage) if mileage is not None else None, engine_volume=vol, power_hp=int(hp) if hp else None,
        fuel=pick("fuel"), transmission=pick("transmission"), drive=pick("drive"), body=pick("body"),
        trim=pick("trim"), vin=pick("vin"), seller_type=seller_type, seller_key=seller_key,
        photos=[x for x in photos if x],
    )


def src_id_from_url(platform: str, url: str) -> str | None:
    if platform == "avito":
        m = re.search(r"_(\d{6,})(?:\?|$|/)", url)
    else:
        m = re.search(r"/(\d{6,})\.html", url)
    return m.group(1) if m else None


class ApiAdSource(SourceAdapter):
    requires_key = True
    status_note = "Реализовано по описанию API; не проверено на реальном ключе."

    def __init__(self, platform: str, api_key: str, base_url: str, queries: list[str], min_interval: float,
                 timeout: float, enrich_per_poll: int = 5, client: httpx.AsyncClient | None = None):
        assert platform in ("avito", "drom")
        self.platform = platform
        self.name = f"apiad_{platform}"
        self.title = f"ApiAd → {'Авито' if platform == 'avito' else 'Дром'}"
        self.api_key, self.base_url = api_key, base_url.rstrip("/")
        self.queries, self.enrich_per_poll = queries, enrich_per_poll
        self.limiter = RateLimiter(min_interval)
        self.client = client or httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "AutoHunter/1.0"})

    def configured(self) -> bool:
        return bool(self.api_key)

    async def _get(self, path: str, params: dict) -> dict | list:
        return await request_json(self.client, self.limiter, "GET", f"{self.base_url}{path}",
                                  params={**params, "apikey": self.api_key})

    async def fetch(self, ctx: FetchContext) -> FetchResult:
        if not self.configured():
            raise SourceNotConfigured("APIAD_API_KEY не задан")
        found: dict[str, dict] = {}
        for q in self.queries:
            data = await self._get(f"/api/{self.platform}/search_transport", {"query": q, "cat": "auto"}
                                   if self.platform == "drom" else {"query": q})
            rows = data if isinstance(data, list) else (data.get("results") or data.get("data") or [])
            if not isinstance(rows, list):
                raise SourceError("search_transport: неожиданный формат ответа")
            for row in rows:
                url = row.get("url") if isinstance(row, dict) else None
                sid = src_id_from_url(self.platform, url or "")
                if sid:
                    found.setdefault(sid, row)
        new_ids = [i for i in found if i not in ctx.known_ids]
        items: list[RawListing] = []
        # известные — отдаём лёгкую запись (title/price из поиска) для отслеживания цены
        for sid, row in found.items():
            if sid in ctx.known_ids:
                items.append(RawListing(source=self.name, source_id=sid, url=row["url"], title=row.get("title") or "",
                                        description=row.get("description") or "", price=int(_num(row.get("price")) or 0) or None,
                                        extra={"light": True}))
        for sid in new_ids[: self.enrich_per_poll]:
            row = found[sid]
            try:
                resp = await self._get(f"/api/{self.platform}/parse_sync", {"url": row["url"]})
            except SourceError:
                continue
            data = resp.get("data") if isinstance(resp, dict) else None
            if not isinstance(data, dict):
                continue
            items.append(raw_from_data(self.platform, sid, data, row.get("price"), row.get("url")))
        return FetchResult(items, ctx.cursor)

    async def aclose(self) -> None:
        await self.client.aclose()

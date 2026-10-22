import asyncio
import time

import httpx
import pytest
import respx

from app.sources.apiad import ApiAdSource, flatten_params, raw_from_data, src_id_from_url
from app.sources.autoru import AutoRuSource
from app.sources.base import FetchContext, RateLimiter, SourceError, SourceNotConfigured, request_json
from app.sources.demo import DemoSource
from app.sources.registry import build_sources

BASE = "https://apiad.test"


def adapter(**kw):
    return ApiAdSource("avito", kw.pop("key", "KEY"), BASE, ["BMW"], 0.0, 5, **kw)


SEARCH = [{"url": "https://www.avito.ru/rostov/avtomobili/bmw_3_seriya_2007_1234567890", "title": "BMW 3 серия, 2007",
           "description": "", "category": "auto", "price": 800000, "price_string": "800 000 ₽"}]
# Форма ответа parse_sync собрана по описанию на apiad.ru; реальный формат не проверен
PARSED = {"success": True, "avitoId": "1234567890", "data": {
    "url": SEARCH[0]["url"], "city": "Ростов-на-Дону", "region": "Ростовская область", "price": 800000,
    "title": "BMW 3 серия, 2007", "description": "Один хозяин", "images": ["https://img.test/1.jpg"],
    "params": {"Пробег": "180 000 км", "Год выпуска": "2007", "Коробка передач": "Автомат", "Объём двигателя": "2.5 л",
               "Тип двигателя": "Бензин", "Привод": "Задний", "Мощность двигателя": "218 л.с."},
    "time_source_created": "2026-10-22T11:32:00Z"}}


@respx.mock
async def test_apiad_parses_search_and_enriches_new_only():
    respx.get(f"{BASE}/api/avito/search_transport").respond(json=SEARCH)
    parse = respx.get(f"{BASE}/api/avito/parse_sync").respond(json=PARSED)
    a = adapter()
    res = await a.fetch(FetchContext())
    assert parse.called and len(res.items) == 1
    it = res.items[0]
    assert (it.source, it.source_id, it.price, it.year, it.mileage) == ("apiad_avito", "1234567890", 800000, 2007, 180000)
    assert it.engine_volume == 2.5 and it.power_hp == 218 and it.posted_at.year == 2026
    assert all(c.request.url.params["apikey"] == "KEY" for c in respx.calls)
    # уже известное объявление — без дорогого parse_sync, только лёгкая запись
    parse.reset()
    res2 = await a.fetch(FetchContext(known_ids={"1234567890"}))
    assert not parse.called and res2.items[0].extra == {"light": True}
    await a.aclose()


@respx.mock
async def test_apiad_enrich_budget_limits_parse_calls():
    rows = [{"url": f"https://www.avito.ru/x/bmw_{1000000 + i}", "title": "BMW", "price": 1} for i in range(10)]
    respx.get(f"{BASE}/api/avito/search_transport").respond(json=rows)
    parse = respx.get(f"{BASE}/api/avito/parse_sync").respond(json=PARSED)
    a = adapter(enrich_per_poll=3)
    await a.fetch(FetchContext())
    assert parse.call_count == 3
    await a.aclose()


async def test_apiad_without_key_not_configured():
    a = adapter(key="")
    assert not a.configured()
    with pytest.raises(SourceNotConfigured):
        await a.fetch(FetchContext())
    await a.aclose()


def test_param_parsing_variants():
    assert flatten_params([{"name": "Пробег", "value": "10 км"}, "Год: 2010"]) == {"пробег": "10 км", "год": "2010"}
    assert src_id_from_url("drom", "https://rostov.drom.ru/bmw/3-series/12345678.html") == "12345678"
    r = raw_from_data("drom", "1", {"url": "u", "price": "1 200 000 ₽", "params": [{"name": "Пробег", "value": "99 000 км"}]})
    assert r.price == 1_200_000 and r.mileage == 99_000


@respx.mock
async def test_retry_on_5xx_then_success(monkeypatch):
    route = respx.get("https://x.test/a").mock(side_effect=[httpx.Response(503), httpx.Response(500), httpx.Response(200, json={"ok": 1})])
    async with httpx.AsyncClient() as c:
        out = await request_json(c, RateLimiter(0), "GET", "https://x.test/a", base_delay=0.01)
    assert out == {"ok": 1} and route.call_count == 3


@respx.mock
async def test_retry_on_network_error_and_429_retry_after():
    respx.get("https://x.test/b").mock(side_effect=[httpx.ConnectTimeout("t"), httpx.Response(429, headers={"Retry-After": "0"}),
                                                    httpx.Response(200, json=[1])])
    async with httpx.AsyncClient() as c:
        assert await request_json(c, RateLimiter(0), "GET", "https://x.test/b", base_delay=0.01) == [1]


@respx.mock
async def test_no_retry_on_403_and_gives_up_after_attempts():
    r403 = respx.get("https://x.test/c").respond(403)
    async with httpx.AsyncClient() as c:
        with pytest.raises(SourceError):
            await request_json(c, RateLimiter(0), "GET", "https://x.test/c", base_delay=0.01)
        assert r403.call_count == 1  # блокировку/капчу не обходим и не долбим
        respx.get("https://x.test/d").respond(500)
        with pytest.raises(SourceError, match="исчерпаны"):
            await request_json(c, RateLimiter(0), "GET", "https://x.test/d", attempts=3, base_delay=0.01)


async def test_rate_limiter_spaces_requests():
    rl = RateLimiter(0.05)
    t = time.monotonic()
    await asyncio.gather(*(rl.acquire() for _ in range(4)))
    assert time.monotonic() - t >= 0.14


async def test_demo_source_deterministic_and_incremental():
    a = DemoSource(seed=1, initial=60, live=True)
    r1 = await a.fetch(FetchContext())
    assert len(r1.items) >= 60 and r1.cursor["bootstrapped"]
    ids = [i.source_id for i in r1.items]
    assert len(set(ids)) == len(ids)
    b = DemoSource(seed=1, initial=60, live=False)
    assert [i.title for i in (await b.fetch(FetchContext())).items[:60]] == [i.title for i in r1.items[:60]]
    r2 = await a.fetch(FetchContext(cursor=r1.cursor))  # повторный вызов не пересоздаёт базу
    assert len(r2.items) <= 3
    assert all(i.is_demo for i in r1.items)


async def test_autoru_is_honest_stub():
    a = AutoRuSource()
    assert not a.configured()
    with pytest.raises(SourceNotConfigured):
        await a.fetch(FetchContext())


def test_registry_builds_only_enabled_and_rejects_unknown(settings):
    settings.sources_enabled = "demo,apiad_avito"
    names = [s.name for s in build_sources(settings)]
    assert names == ["demo", "apiad_avito"]
    settings.sources_enabled = "nonexistent"
    with pytest.raises(ValueError):
        build_sources(settings)

import asyncio

import httpx
import pytest
import pytest_asyncio

from app.api.auth import SlidingWindow, create_token, verify_token
from app.config import Settings
from app.main import create_app
from app.sources.demo import DemoSource


@pytest_asyncio.fixture
async def client(settings):
    app = create_app(settings, adapters=[DemoSource(42, 150, live=False)], background=False)
    async with app.router.lifespan_context(app):
        # заполняем БД демо-данными напрямую, без фоновых циклов
        from app.runner import SourceRunner
        await SourceRunner(app.state.adapters[0], app.state.db, app.state.pipeline, app.state.notifier, settings).run_once()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post("/api/auth/login", json={"password": "pw-test"})
            c.headers["Authorization"] = f"Bearer {r.json()['token']}"
            c.app = app
            yield c


async def test_auth_required_and_login(settings, client):
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://t")
    assert (await anon.get("/api/monitoring")).status_code == 401
    assert (await anon.get("/api/healthz")).status_code == 200
    assert (await anon.post("/api/auth/login", json={"password": "wrong"})).status_code == 401
    bad = await anon.get("/api/meta", headers={"Authorization": "Bearer abc.def"})
    assert bad.status_code == 401
    await anon.aclose()


def test_token_expiry_and_tamper():
    t = create_token("secret" * 3, 1, now=1000)
    assert verify_token("secret" * 3, t, now=1500)
    assert not verify_token("secret" * 3, t, now=1000 + 3601)
    assert not verify_token("other-secret-xx", t, now=1500)
    assert not verify_token("secret" * 3, t[:-2] + "xx", now=1500)


def test_sliding_window_limiter():
    w = SlidingWindow(3, 10)
    assert [w.allow("ip", now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert w.allow("ip", now=11)


async def test_login_rate_limited(client):
    anon = httpx.AsyncClient(transport=httpx.ASGITransport(app=client.app), base_url="http://t")
    codes = [(await anon.post("/api/auth/login", json={"password": "x"})).status_code for _ in range(12)]
    assert 429 in codes
    await anon.aclose()


def test_production_refuses_default_secrets():
    with pytest.raises(RuntimeError, match="AUTH_PASSWORD"):
        create_app(Settings(app_env="production", auth_password="change-me"), background=False)


async def test_search_filters_sort_and_pagination(client):
    r = await client.post("/api/listings/search", json={"filter": {"brands": ["BMW"], "price_max": 1_000_000}, "sort": "score", "limit": 10})
    d = r.json()
    assert r.status_code == 200 and d["total"] > 0 and len(d["items"]) <= 10
    assert all(i["brand"] == "BMW" and i["price"] <= 1_000_000 for i in d["items"])
    scores = [i["score"] for i in d["items"]]
    assert scores == sorted(scores, reverse=True)
    page2 = (await client.post("/api/listings/search", json={"filter": {"brands": ["BMW"]}, "limit": 5, "offset": 5})).json()
    page1 = (await client.post("/api/listings/search", json={"filter": {"brands": ["BMW"]}, "limit": 5})).json()
    assert not {i["id"] for i in page1["items"]} & {i["id"] for i in page2["items"]}
    assert (await client.post("/api/listings/search", json={"sort": "bogus"})).status_code == 422
    deals = (await client.post("/api/listings/search", json={"filter": {"deviation_min": 10}})).json()
    assert all(i["deviation_pct"] >= 10 for i in deals["items"])


async def test_listing_detail_explains_valuation(client):
    item = (await client.post("/api/listings/search", json={"limit": 1, "sort": "score"})).json()["items"][0]
    d = (await client.get(f"/api/listings/{item['id']}")).json()
    assert d["price_history"] and d["valuation"]["explain"]["disclaimer"]
    assert d["valuation"]["explain"]["tier"] and 0 <= d["confidence"] <= 1
    assert d["score_parts"]["price"] and "comparables" in d
    assert (await client.get("/api/listings/999999")).status_code == 404


async def test_favorite_hide_roundtrip(client):
    item = (await client.post("/api/listings/search", json={"limit": 1})).json()["items"][0]
    assert (await client.post(f"/api/listings/{item['id']}/favorite")).json() == {"favorite": True}
    favs = (await client.post("/api/listings/search", json={"filter": {"only_favorites": True}})).json()
    assert favs["total"] == 1
    await client.post(f"/api/listings/{item['id']}/hide")
    hidden = (await client.post("/api/listings/search", json={"filter": {"q": item["title"]}})).json()
    assert item["id"] not in {i["id"] for i in hidden["items"]}


async def test_profiles_crud_and_default_seeded(client):
    profs = (await client.get("/api/profiles")).json()
    assert len(profs) == 2 and profs[0]["filters"]["price_min"] == 500_000 and "BMW" in profs[0]["filters"]["brands"]
    body = {"name": "Мой Audi", "filters": {"brands": ["Audi"], "price_max": 900000}, "notify_min_score": 60}
    created = (await client.post("/api/profiles", json=body)).json()
    assert (await client.post("/api/profiles", json=body)).status_code == 409
    body["name"] = "Audi 2"
    upd = (await client.put(f"/api/profiles/{created['id']}", json=body)).json()
    assert upd["name"] == "Audi 2"
    assert (await client.delete(f"/api/profiles/{created['id']}")).json() == {"ok": True}
    assert (await client.put("/api/profiles/9999", json=body)).status_code == 404
    assert (await client.post("/api/profiles", json={"name": "x", "filters": {"price_min": "abc"}})).status_code == 422


async def test_analytics_and_meta(client):
    a = (await client.post("/api/analytics", json={"brands": ["BMW"]})).json()
    assert a["count"] > 0 and a["median_price"] and len(a["histogram"]) == 12
    assert sum(b["count"] for b in a["histogram"]) == a["count"]
    assert a["by_generation"] and a["liquidity"] and a["trend"] and a["note"]
    m = (await client.get("/api/meta")).json()
    assert set(m["brands"]) <= {"BMW", "Mercedes-Benz", "Audi"} and m["demo_mode"] is True


async def test_monitoring(client):
    m = (await client.get("/api/monitoring")).json()
    src = m["sources"][0]
    assert src["name"] == "demo" and src["is_demo"] and src["last_success_at"] and src["processed_total"] > 0
    assert src["detection_latency_s"]["synthetic"] and src["detection_latency_s"]["samples"] == 0  # первичная загрузка не считается
    from conftest import raw
    async with client.app.state.db.session() as s:
        await client.app.state.pipeline.ingest(s, [raw(str(i), source="demo", title=f"BMW 320i 2010 #{i}", price=700_000 + i * 1000) for i in range(20)])
        await s.commit()
    m = (await client.get("/api/monitoring")).json()
    lat = m["sources"][0]["detection_latency_s"]
    assert lat["samples"] == 20 and 15 < lat["avg"] < 30 and lat["p95"] >= lat["avg"]
    assert m["telegram"]["mode"] == "stub" and m["total_listings"] > 0


async def test_settings_validation_and_revalue(client):
    s = (await client.get("/api/settings")).json()
    assert s["scoring"]["thresholds"] == {"great": 85, "good": 70, "normal": 50}
    bad = await client.put("/api/settings", json={"scoring": {"thresholds": {"great": 60, "good": 70, "normal": 50}}})
    assert bad.status_code == 422
    assert (await client.put("/api/settings", json={"valuation": {"nope": 1}})).status_code == 422
    ok = await client.put("/api/settings", json={"scoring": {"weights": {"price": 60}}, "valuation": {"asking_discount": 0.1}})
    assert ok.json()["scoring"]["weights"]["price"] == 60 and ok.json()["valuation"]["asking_discount"] == 0.1
    assert (await client.post("/api/revalue")).json()["revalued"] > 0


async def test_telegram_test_notification_stub(client):
    r = await client.post("/api/telegram/test")
    assert r.status_code == 200 and r.json()["mode"] == "stub"
    assert "ТЕСТ" in r.json()["preview"] and "Оценка AutoHunter" in r.json()["preview"]
    sent = client.app.state.notifier.transport.sent
    assert sent and sent[-1][3][0][0].url


async def test_full_app_starts_in_demo_mode_without_keys(settings):
    """Критерий готовности: запуск без ключей API → появляются объявления с оценками; остановка чистая."""
    settings.demo_live = True
    app = create_app(settings, background=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            tok = (await c.post("/api/auth/login", json={"password": "pw-test"})).json()["token"]
            h = {"Authorization": f"Bearer {tok}"}
            for _ in range(100):
                d = (await c.post("/api/listings/search", json={}, headers=h)).json()
                if d["total"] > 50:
                    break
                await asyncio.sleep(0.1)
            assert d["total"] > 50 and all(i["score"] is not None for i in d["items"])

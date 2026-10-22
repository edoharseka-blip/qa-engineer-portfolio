from datetime import timedelta

from sqlalchemy import func, select

from app.models import Listing, Notification, SearchProfile
from app.notifier import LogTransport, Notifier, format_listing, listing_buttons
from app.pipeline import Pipeline
from app.store import ensure_default_profiles, kv_set
from app.timeutil import utcnow
from conftest import raw


async def setup(db, settings, items, chats=(111,)):
    settings.telegram_allowed_chat_ids = ",".join(map(str, chats))
    tr = LogTransport()
    n = Notifier(settings, tr)
    async with db.session() as s:
        await ensure_default_profiles(s)
        p = (await s.execute(select(SearchProfile).order_by(SearchProfile.id))).scalars().first()
        p.notify_min_score, p.notify_min_deviation = 0, 0.0  # уведомлять обо всём подходящем по фильтру
        p.filters = {"brands": ["BMW"]}
        await s.commit()
        res = await Pipeline().ingest(s, items)
        await s.commit()
    return n, tr, res


async def test_message_format_contains_required_fields(db, settings):
    n, tr, res = await setup(db, settings, [raw("1", price=800_000)])
    async with db.session() as s:
        l = (await s.execute(select(Listing))).scalar_one()
        l.market_price, l.deviation_pct, l.confidence, l.score, l.score_label = 930_000, 14.0, 0.8, 87, "very_interesting"
        text = format_listing(l)
        assert "800 000 ₽" in text and "930 000 ₽" in text and "Ниже рынка: <b>14%</b>" in text
        assert "87/100" in text and "очень интересное предложение" in text and "Источник" in text and "Обнаружено" in text
        assert "Пробег: 150 000 км" in text
        kb = listing_buttons(l)
        assert [b.text for row in kb for b in row][0].endswith("Открыть объявление") and kb[0][0].url == l.url
        assert {b.callback.split(":")[0] for row in kb for b in row if b.callback} == {"comps", "fav", "hide"}


async def test_no_duplicate_notifications(db, settings):
    n, tr, res = await setup(db, settings, [raw("1")])
    async with db.session() as s:
        l = (await s.execute(select(Listing))).scalar_one()
        assert await n.maybe_notify(s, l) == 1
        assert await n.maybe_notify(s, l) == 0
        assert await n.maybe_notify(s, l, price_changed=True) == 0  # цена не менялась
        assert (await s.execute(select(func.count(Notification.id)))).scalar_one() == 1
        assert l.notified_at is not None
    assert len(tr.sent) == 1


async def test_significant_price_drop_renotifies_once(db, settings):
    n, tr, res = await setup(db, settings, [raw("1", price=900_000)])
    p = Pipeline()
    async with db.session() as s:
        l = (await s.execute(select(Listing))).scalar_one()
        await n.maybe_notify(s, l)
        await p.ingest(s, [raw("1", price=890_000)])  # -1%: мало
        await s.commit()
        assert await n.maybe_notify(s, l, price_changed=True) == 0
        res = await p.ingest(s, [raw("1", price=800_000)])  # -11%
        await s.commit()
        assert res.price_changes == 1
        assert await n.maybe_notify(s, l, price_changed=True) == 1
        assert await n.maybe_notify(s, l, price_changed=True) == 0
    assert "Цена снижена" in tr.sent[-1][1] and "900 000" in tr.sent[-1][1]


async def test_pause_hidden_filter_and_stale(db, settings):
    n, tr, res = await setup(db, settings, [raw("1"), raw("2", title="Audi A4 2.0 TFSI 2010"),
                                            raw("3", posted_at=utcnow() - timedelta(days=5))])
    async with db.session() as s:
        ls = {l.source_id: l for l in (await s.execute(select(Listing))).scalars()}
        assert await n.maybe_notify(s, ls["2"]) == 0      # не подходит под фильтр (марка)
        assert await n.maybe_notify(s, ls["3"]) == 0      # старое — бэкфилл не рассылаем
        await kv_set(s, "notifications_paused", True)
        assert await n.maybe_notify(s, ls["1"]) == 0      # пауза
        await kv_set(s, "notifications_paused", False)
        ls["1"].hidden = True
        assert await n.maybe_notify(s, ls["1"]) == 0      # скрыто
        ls["1"].hidden = False
        assert await n.maybe_notify(s, ls["1"]) == 1
    assert len(tr.sent) == 1


async def test_failed_send_releases_claim_for_retry(db, settings):
    n, tr, res = await setup(db, settings, [raw("1")])

    class Broken:
        calls = 0

        async def send(self, *a):
            Broken.calls += 1
            if Broken.calls == 1:
                raise RuntimeError("telegram down")
            tr.sent.append(a)

    n.transport = Broken()
    async with db.session() as s:
        l = (await s.execute(select(Listing))).scalar_one()
        assert await n.maybe_notify(s, l) == 0
        assert (await s.execute(select(func.count(Notification.id)))).scalar_one() == 0
        assert await n.maybe_notify(s, l) == 1


async def test_score_threshold_applies(db, settings):
    n, tr, res = await setup(db, settings, [raw("1")])
    async with db.session() as s:
        p = (await s.execute(select(SearchProfile).order_by(SearchProfile.id))).scalars().first()
        p.notify_min_score, p.notify_min_deviation = 101, 999.0
        await s.commit()
        l = (await s.execute(select(Listing))).scalar_one()
        assert await n.maybe_notify(s, l) == 0
        p.notify_min_score = 0
        await s.commit()
        assert await n.maybe_notify(s, l) == 1

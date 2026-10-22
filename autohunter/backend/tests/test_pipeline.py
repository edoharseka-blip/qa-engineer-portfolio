from sqlalchemy import func, select

from app.db import Database
from app.models import Listing, PriceHistory
from app.pipeline import Pipeline
from app.sources.base import FetchContext
from app.sources.demo import DemoSource
from conftest import raw


async def seed(db, n=120):
    src = DemoSource(seed=42, initial=n, live=False)
    items = (await src.fetch(FetchContext())).items
    async with db.session() as s:
        res = await Pipeline().ingest(s, items)
        await s.commit()
    return items, res


async def test_demo_ingest_valuates_and_scores(db):
    items, res = await seed(db)
    assert res.new + res.duplicates + res.rejected == len(items)
    async with db.session() as s:
        rows = (await s.execute(select(Listing).where(Listing.dup_of_id.is_(None)))).scalars().all()
        assert rows and all(l.score is not None and 0 <= l.score <= 100 for l in rows)
        valued = [l for l in rows if l.market_price]
        assert len(valued) > 0.8 * len(rows)
        assert all(l.valuation["explain"]["disclaimer"] for l in valued) and all(l.confidence is not None for l in rows)
        assert {l.brand for l in rows} <= {"BMW", "Mercedes-Benz", "Audi"}


async def test_reingest_unchanged_does_not_reprocess(db):
    items, first = await seed(db)
    async with db.session() as s:
        again = await Pipeline().ingest(s, items)
        await s.commit()
        n = (await s.execute(select(func.count(Listing.id)))).scalar_one()
    assert again.new == 0 and again.updated == 0 and again.price_changes == 0
    assert again.unchanged > 0
    assert n == first.new + first.duplicates


async def test_price_change_recorded_in_history(db):
    p = Pipeline()
    async with db.session() as s:
        await p.ingest(s, [raw("a", price=900_000)])
        await s.commit()
        res = await p.ingest(s, [raw("a", price=850_000)])
        await s.commit()
        l = (await s.execute(select(Listing).where(Listing.source_id == "a"))).scalar_one()
        hist = (await s.execute(select(PriceHistory.price).where(PriceHistory.listing_id == l.id)
                                .order_by(PriceHistory.id))).scalars().all()
    assert res.price_changes == 1 and hist == [900_000, 850_000]
    assert l.price == 850_000 and l.price_initial == 900_000


async def test_duplicate_across_sources_is_linked_not_counted(db):
    p = Pipeline()
    async with db.session() as s:
        await p.ingest(s, [raw("a", source="avito", price=900_000)])
        res = await p.ingest(s, [raw("zz", source="drom", price=890_000, description="Пробег 150 200 км, автомат, бензин 2.5")])
        await s.commit()
        rows = (await s.execute(select(Listing).order_by(Listing.id))).scalars().all()
    assert res.duplicates == 1 and res.new == 0
    assert rows[1].dup_of_id == rows[0].id and rows[0].repost_count == 1
    assert rows[1].id not in res.new_ids


async def test_invalid_items_rejected_not_fatal(db):
    async with db.session() as s:
        res = await Pipeline().ingest(s, [raw("1", price=0), raw("2", title="Lada Vesta"), raw("3")])
        await s.commit()
    assert res.rejected == 2 and res.new == 1


async def test_data_persists_after_restart(settings):
    d1 = Database(settings.database_url)
    await d1.create_all()
    await seed(d1, 60)
    await d1.dispose()
    d2 = Database(settings.database_url)
    async with d2.session() as s:
        assert (await s.execute(select(func.count(Listing.id)))).scalar_one() > 50
    await d2.dispose()


async def test_detection_timestamps_stored(db):
    async with db.session() as s:
        await Pipeline().ingest(s, [raw("t")])
        await s.commit()
        l = (await s.execute(select(Listing))).scalar_one()
    assert l.posted_at and l.first_seen_at and 0 <= (l.first_seen_at - l.posted_at).total_seconds() < 60


async def test_stale_listings_deactivated(db):
    from datetime import timedelta
    from app.timeutil import utcnow
    p = Pipeline()
    async with db.session() as s:
        await p.ingest(s, [raw("old")])
        l = (await s.execute(select(Listing))).scalar_one()
        l.last_seen_at = utcnow() - timedelta(hours=100)
        await s.commit()
        assert await p.deactivate_stale(s, 72) == 1

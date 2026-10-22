from datetime import timedelta

import pytest
from sqlalchemy import select

from app.filters import apply_filter, matches
from app.models import Listing
from app.schemas import ListingFilter
from app.timeutil import utcnow
from test_pipeline import seed

CASES = [
    ListingFilter(),
    ListingFilter(brands=["BMW"]),
    ListingFilter(brands=["BMW", "Audi"], price_min=500_000, price_max=1_000_000),
    ListingFilter(year_min=2009, year_max=2013, transmissions=["AT"]),
    ListingFilter(regions=["Ростовская область", "Краснодарский край"], seller_types=["private"]),
    ListingFilter(regions=["Москва"], cities=["Ростов-на-Дону"]),
    ListingFilter(deviation_min=10),
    ListingFilter(score_min=50, mileage_max=150_000),
    ListingFilter(fuels=["diesel"], drives=["AWD"]),
    ListingFilter(engine_volume_min=2.0, engine_volume_max=2.5),
    ListingFilter(q="Автомат"),
    ListingFilter(q="bmw 3"),
    ListingFilter(posted_after=utcnow() - timedelta(days=3)),
    ListingFilter(models=["X5", "Q7"], include_duplicates=True),
]


@pytest.mark.parametrize("f", CASES, ids=lambda f: f.model_dump_json(exclude_defaults=True)[:60])
async def test_sql_and_python_filters_agree(db, f):
    await seed(db, 200)
    async with db.session() as s:
        all_rows = (await s.execute(select(Listing))).scalars().all()
        sql_ids = {l.id for l in (await s.execute(apply_filter(select(Listing), f))).scalars()}
    py_ids = {l.id for l in all_rows if matches(l, f)}
    assert sql_ids == py_ids


async def test_filter_semantics(db):
    await seed(db, 200)
    async with db.session() as s:
        f = ListingFilter(brands=["Audi"], price_max=900_000, regions=["Ростовская область"])
        rows = (await s.execute(apply_filter(select(Listing), f))).scalars().all()
        assert rows
        assert all(l.brand == "Audi" and l.price <= 900_000 and l.region == "Ростовская область" for l in rows)
        assert all(l.dup_of_id is None and not l.hidden for l in rows)
        l0 = rows[0]
        l0.hidden = True
        await s.commit()
        again = (await s.execute(apply_filter(select(Listing), f))).scalars().all()
        assert l0.id not in {l.id for l in again}
        with_hidden = (await s.execute(apply_filter(select(Listing), f.model_copy(update={"include_hidden": True})))).scalars().all()
        assert l0.id in {l.id for l in with_hidden}

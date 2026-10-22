import math
import random
import statistics

from app.valuation import estimate
from conftest import car


def synthetic_pool(n=40, seed=1, base=1_000_000, region="Ростовская область"):
    rng = random.Random(seed)
    pool = []
    for _ in range(n):
        year = rng.randint(2007, 2010)
        km = rng.randint(100_000, 220_000)
        price = base * math.exp(-0.045 * (year - 2008) * -1) * (1 - 0.005 * (km - 150_000) / 10_000)
        pool.append(car(year=year, mileage=km, price=int(price * rng.uniform(0.96, 1.04)), region=region))
    return pool


def test_estimate_close_to_ground_truth_and_deviation_sign():
    pool = synthetic_pool()
    t = car(year=2008, mileage=150_000, price=800_000)
    v = estimate(t, pool)
    assert v.market_price and abs(v.market_price - 1_000_000) / 1_000_000 < 0.06
    assert v.deviation_pct > 15  # цена ниже рынка
    assert v.comps_count >= 6 and v.confidence > 0.6
    assert v.explain["disclaimer"] and v.explain["expected_sale_price"] < v.market_price


def test_outliers_do_not_move_median():
    pool = synthetic_pool()
    clean = estimate(car(year=2008, mileage=150_000), pool).market_price
    dirty = pool + [car(year=2008, mileage=150_000, price=50_000), car(year=2008, mileage=150_000, price=9_000_000),
                    car(year=2008, mileage=151_000, price=60_000)]
    v = estimate(car(year=2008, mileage=150_000), dirty)
    assert abs(v.market_price - clean) / clean < 0.03
    assert v.explain["outliers_removed"] >= 2
    mean = statistics.fmean(c.price for c in dirty)
    assert abs(mean - clean) > abs(v.market_price - clean)  # простое среднее было бы хуже


def test_duplicates_in_pool_are_collapsed():
    base = synthetic_pool(8)
    twin = [car(year=base[0].year, mileage=base[0].mileage, price=base[0].price, region=base[0].region) for _ in range(5)]
    v = estimate(car(year=2008, mileage=150_000), base + twin)
    assert v.explain["duplicates_removed"] >= 4
    flagged = [car(year=2008, mileage=150_000, price=10, dup_of_id=1)]
    assert estimate(car(year=2008, mileage=150_000), base + flagged).comps_count == v.comps_count


def test_mileage_and_year_adjustments():
    pool = synthetic_pool(60, seed=3)
    low = estimate(car(year=2008, mileage=80_000), pool).market_price
    high = estimate(car(year=2008, mileage=250_000), pool).market_price
    assert low > high
    assert estimate(car(year=2010, mileage=150_000), pool).market_price > estimate(car(year=2007, mileage=150_000), pool).market_price


def test_insufficient_data_is_explicit():
    v = estimate(car(), [car(), car()])
    assert v.market_price is None and v.deviation_pct is None and v.confidence == 0
    assert v.tier == "недостаточно данных"
    assert estimate(car(brand="Audi", model="A4", generation="B8"), synthetic_pool()).market_price is None


def test_widening_criteria_lowers_confidence():
    exact = synthetic_pool(30)
    v1 = estimate(car(year=2008, mileage=150_000), exact)
    # аналоги только из другого региона, других годов → нужно расширение
    far = [c for c in synthetic_pool(30)]
    for c in far:
        c.year += 3
        c.region = "Москва"
    v2 = estimate(car(year=2008, mileage=150_000, transmission=None, fuel=None), far)
    assert v2.market_price and v2.explain["tier_index"] > v1.explain["tier_index"]
    assert v2.confidence < v1.confidence


def test_few_comps_flagged_as_approximate():
    pool = synthetic_pool(4)
    v = estimate(car(year=2008, mileage=150_000), pool)
    assert v.market_price and any("ориентировоч" in n for n in v.explain["notes"])
    assert v.confidence < estimate(car(year=2008, mileage=150_000), synthetic_pool(30)).confidence


def test_unknown_mileage_noted():
    v = estimate(car(year=2008, mileage=None), synthetic_pool())
    assert any("пробег неизвестен" in n for n in v.explain["notes"])

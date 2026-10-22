from app.dedupe import fingerprint, is_duplicate
from conftest import car


def test_same_car_other_source_is_duplicate():
    a, b = car(price=800_000), car(price=780_000, mileage=150_200, id=None)
    assert is_duplicate(a, b) == "attrs"


def test_same_seller_is_stronger_signal():
    a, b = car(seller_key="x"), car(seller_key="x", city="Другой")
    assert is_duplicate(a, b) == "seller+attrs"


def test_vin_decides():
    assert is_duplicate(car(vin="WBAVB11111111111"), car(vin="WBAVB11111111111", mileage=1)) == "vin"
    assert is_duplicate(car(vin="WBAVB11111111111"), car(vin="WBAVB22222222222")) is None


def test_different_cars_not_duplicates():
    base = car()
    assert is_duplicate(base, car(mileage=190_000)) is None
    assert is_duplicate(base, car(year=2009)) is None
    assert is_duplicate(base, car(price=1_300_000)) is None
    assert is_duplicate(base, car(transmission="MT")) is None
    assert is_duplicate(base, car(region="Москва")) is None
    assert is_duplicate(base, car(mileage=None)) is None


def test_fingerprint_collapses_only_identical():
    assert fingerprint(car(mileage=150_100)) == fingerprint(car(mileage=150_200))
    assert fingerprint(car(mileage=150_000)) != fingerprint(car(mileage=170_000))
    assert fingerprint(car(mileage=None)) is None

import pytest

from app.normalize import ValidationError, normalize
from conftest import raw


def test_brand_model_generation_from_title():
    n = normalize(raw(title="БМВ 325i E90, 2007"))
    assert (n.brand, n.model, n.generation, n.year) == ("BMW", "3 Series", "E90", 2007)
    assert n.engine_volume == 2.5 and n.fuel == "petrol"  # 2.5 из описания/названия


def test_mercedes_and_audi_variants():
    m = normalize(raw(title="Mercedes-Benz E 250 CDI 2012", description="150 тыс. км, АКПП"))
    assert (m.brand, m.model, m.generation, m.fuel, m.mileage) == ("Mercedes-Benz", "E-Class", "W212", "diesel", 150_000)
    a = normalize(raw(title="Ауди A6 2.0 TFSI quattro", description="2014 г. 98 000 км"))
    assert (a.brand, a.model, a.year, a.drive, a.mileage) == ("Audi", "A6", 2014, "AWD", 98_000)
    g = normalize(raw(title="Mercedes GLK 250 4matic 2013"))
    assert g.model == "GLK" and g.drive == "AWD"


def test_x_series_not_confused_with_series_number():
    assert normalize(raw(title="BMW X5 xDrive30d, 2010")).model == "X5"
    assert normalize(raw(title="BMW 530d F10 2013")).model == "5 Series"


def test_structured_fields_win_over_text():
    n = normalize(raw(title="BMW 320i", brand="BMW", model="3 серии", year=2010, mileage=90_000, transmission="Автомат",
                      fuel="Бензин", drive="Задний", region="Ростовская область"))
    assert (n.model, n.year, n.mileage, n.transmission, n.fuel, n.drive) == ("3 Series", 2010, 90_000, "AT", "petrol", "RWD")


def test_region_from_city_and_seller_normalization():
    n = normalize(raw(city="Краснодар", seller_type="Частное лицо"))
    assert n.region == "Краснодарский край" and n.seller_type == "private"
    assert normalize(raw(seller_type="Автосалон")).seller_type == "dealer"


@pytest.mark.parametrize("kw", [dict(price=0), dict(price=-5), dict(price=10**10), dict(price=None),
                                dict(title="Lada Vesta 2020"), dict(year=1950), dict(mileage=-1),
                                dict(source_id=""), dict(url="")])
def test_invalid_listings_rejected(kw):
    with pytest.raises(ValidationError):
        normalize(raw(**kw))


def test_content_hash_changes_with_price():
    assert normalize(raw(price=800_000)).content_hash != normalize(raw(price=790_000)).content_hash
    assert normalize(raw()).content_hash == normalize(raw()).content_hash


def test_photos_filtered_to_http_urls():
    n = normalize(raw(photos=["javascript:alert(1)", "https://x.test/1.jpg", "ftp://x"]))
    assert n.photos == ["https://x.test/1.jpg"]

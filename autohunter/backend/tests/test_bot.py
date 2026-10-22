import pytest

from app.bot import apply_setting, describe_profile, to_markup
from app.models import SearchProfile
from app.notifier import Button


def prof():
    return SearchProfile(name="p", filters={"price_min": 500000, "brands": ["BMW"]}, notify_min_score=70, notify_min_deviation=10.0)


def test_set_numeric_lists_and_thresholds():
    p = prof()
    apply_setting(p, "price_max", "900 000")
    apply_setting(p, "brands", "BMW, Audi")
    apply_setting(p, "seller", "private")
    apply_setting(p, "min_score", "80")
    apply_setting(p, "min_dev", "12.5")
    assert p.filters["price_max"] == 900_000 and p.filters["brands"] == ["BMW", "Audi"]
    assert p.filters["seller_types"] == ["private"] and p.notify_min_score == 80 and p.notify_min_deviation == 12.5
    apply_setting(p, "price_max", "none")
    assert "price_max" not in p.filters


def test_set_rejects_garbage():
    with pytest.raises(ValueError):
        apply_setting(prof(), "bogus", "1")
    with pytest.raises(ValueError):
        apply_setting(prof(), "price_max", "много")
    with pytest.raises(KeyError):
        apply_setting(prof(), "seller", "alien")


def test_describe_and_markup():
    assert "500 000 ₽" in describe_profile(prof())
    m = to_markup([[Button("a", url="https://x.test")], [Button("b", callback="fav:1"), Button("c", callback="hide:1")]])
    assert m.inline_keyboard[0][0].url == "https://x.test" and m.inline_keyboard[1][1].callback_data == "hide:1"

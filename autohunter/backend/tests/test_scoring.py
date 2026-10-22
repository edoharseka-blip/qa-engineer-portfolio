from datetime import timedelta

from app.scoring import ScoringConfig, analyze_text, compute_score, label_for, liquidity_estimate
from app.timeutil import utcnow
from conftest import car


class L:
    def __init__(self, **kw):
        d = dict(deviation_pct=15.0, confidence=0.8, year=2012, mileage=130_000, title="BMW 520i", description="",
                 first_seen_at=utcnow(), posted_at=utcnow() - timedelta(days=2), price=900_000, seller_type="private",
                 repost_count=0)
        d.update(kw)
        self.__dict__.update(d)


def score(**kw):
    cfg = kw.pop("cfg", ScoringConfig())
    hist = kw.pop("hist", [(900_000, utcnow())])
    return compute_score(L(**kw), cfg, kw.get("liq", 0.85), hist)


def test_cheaper_is_better_and_labels():
    a, b = score(deviation_pct=25), score(deviation_pct=0)
    assert a.score > b.score
    cfg = ScoringConfig()
    assert label_for(85, cfg) == "very_interesting" and label_for(70, cfg) == "worth_a_look"
    assert label_for(50, cfg) == "normal" and label_for(49, cfg) == "low"


def test_low_confidence_shrinks_price_effect():
    assert score(confidence=0.9).score > score(confidence=0.2).score


def test_problem_text_warns_and_caps_even_if_cheap():
    r = score(deviation_pct=30, description="Была в ДТП, требует вложений", cfg=ScoringConfig(risk_cap=60))
    assert r.score <= 60
    assert any("ДТП" in w for w in r.warnings)


def test_suspiciously_cheap_gets_warning_and_cap():
    r = score(deviation_pct=45)
    assert any("подозрительно дёшево" in w for w in r.warnings) and r.score <= 69


def test_missing_valuation_is_explicit():
    r = score(deviation_pct=None, confidence=None)
    assert any("недоступна" in w for w in r.warnings)


def test_weights_and_thresholds_configurable():
    heavy_price = ScoringConfig.from_dict({"weights": {"price": 90, "liquidity": 1, "mileage": 1, "age": 1, "condition": 1,
                                                       "price_history": 1, "confidence": 1}})
    assert score(deviation_pct=25, cfg=heavy_price).score > score(deviation_pct=25).score
    strict = ScoringConfig.from_dict({"thresholds": {"great": 99, "good": 95, "normal": 90}})
    assert score(cfg=strict).label == "low"


def test_price_history_drop_and_stale_and_repost():
    drop = score(hist=[(1_000_000, utcnow() - timedelta(days=3)), (900_000, utcnow())])
    flat = score()
    assert drop.parts["price_history"]["value"] > flat.parts["price_history"]["value"]
    stale = score(posted_at=utcnow() - timedelta(days=80))
    assert stale.parts["price_history"]["value"] < flat.parts["price_history"]["value"]
    assert score(repost_count=2).parts["price_history"]["value"] < flat.parts["price_history"]["value"]


def test_private_bonus_and_unknown_mileage():
    assert score(seller_type="private").score >= score(seller_type="dealer").score
    assert any("пробег" in w for w in score(mileage=None).warnings)


def test_text_analysis():
    s, w, serious = analyze_text("Один хозяин, не бит, не крашен, обслужен")
    assert s > 0.8 and not serious and not w
    assert analyze_text("продаю на запчасти, скручен пробег")[2]


def test_liquidity_blends_prior_and_data():
    assert liquidity_estimate(None, []) is None
    assert liquidity_estimate(0.8, [5, 6, 7]) == 0.72  # данных мало — только prior (консервативно)
    fast = liquidity_estimate(0.8, [3, 4, 5, 6, 7, 8])
    slow = liquidity_estimate(0.8, [60, 70, 80, 90, 100, 120])
    assert fast > slow

"""Рейтинг 0–100. Выгода цены и техническое состояние оцениваются раздельно; признаки проблем
дают предупреждения и ограничивают итог сверху (risk_cap), а не «растворяются» в сумме."""
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .timeutil import utcnow


@dataclass
class ScoringConfig:
    weights: dict = field(default_factory=lambda: {
        "price": 45, "liquidity": 15, "mileage": 10, "age": 8, "condition": 10, "price_history": 4,
        "confidence": 8})
    thresholds: dict = field(default_factory=lambda: {"great": 85, "good": 70, "normal": 50})
    private_bonus: float = 3.0       # баллы за частного продавца (приоритет по настройкам)
    risk_cap: int = 69               # потолок при серьёзных рисках
    suspicious_deviation: float = 35.0  # «подозрительно дёшево» от этого % ниже рынка
    km_per_year: int = 15000

    @classmethod
    def from_dict(cls, d: dict | None) -> "ScoringConfig":
        c = cls()
        if d:
            c.weights = {**c.weights, **d.get("weights", {})}
            c.thresholds = {**c.thresholds, **d.get("thresholds", {})}
            for k in ("private_bonus", "risk_cap", "suspicious_deviation", "km_per_year"):
                if k in d:
                    setattr(c, k, d[k])
        return c

    def to_dict(self) -> dict:
        return asdict(self)


SERIOUS = [
    (r"(?<!без )(?<!без\s)\bдтп\b|битый|битая|аварийн|не\s+на\s+ходу|на\s+запчасти|под\s+восстановлен",
     "в описании признаки ДТП/неисправности"),
    (r"требует\s+вложени|требуется\s+ремонт|нужен\s+ремонт|проблем\w*\s+с\s+(двигател|коробк|акпп)|стучит|троит|течь|течёт",
     "в описании упомянуты неисправности"),
    (r"скрученн|не\s+родной\s+пробег|пробег\s+скручен", "возможна скрутка пробега"),
    (r"дубликат\s+пТС|дубликат\s+птс|без\s+птс|залог|в\s+кредит|ограничени|арест|утилизац",
     "проблемы с документами/обременения"),
]
MILD = [
    (r"торг\s+при\s+осмотре|срочно|срочная\s+продажа", "срочная продажа (возможен торг)"),
    (r"(?<!не )(?<!не\s)крашен|окрашен|есть\s+окрас|мелкие\s+дефекты|сколы", "упомянуты окрасы/дефекты кузова"),
]
POSITIVE = [
    r"один\s+хозяин|1\s+хозяин|единственный\s+владелец", r"обслужен|то\s+у\s+дилера|сервисная\s+книжка|все\s+то",
    r"не\s+бит|не\s+крашен|без\s+дтп", r"родной\s+пробег|пробег\s+подтвержд", r"отличное\s+состояние|идеальн",
    r"полная\s+комплектация|максимальн\w+\s+комплектац|full",
]


def _clamp(x: float, lo=0.0, hi=1.0) -> float:
    return max(lo, min(hi, x))


def analyze_text(text: str) -> tuple[float, list[str], bool]:
    low = text.lower()
    warnings, serious, mild = [], False, 0
    for pat, msg in SERIOUS:
        if re.search(pat, low, re.I):
            warnings.append("⚠️ " + msg)
            serious = True
    for pat, msg in MILD:
        if re.search(pat, low, re.I):
            warnings.append(msg)
            mild += 1
    pos = sum(bool(re.search(p, low, re.I)) for p in POSITIVE)
    s = 0.5 + 0.12 * pos - (0.35 if serious else 0) - 0.05 * mild
    return _clamp(s), warnings, serious


def price_history_score(history: list[tuple[int, datetime]], current: int, days_on_market: float,
                        reposts: int) -> tuple[float, str]:
    if not history:
        return 0.5, "истории цены нет"
    first = history[0][0]
    change = (first - current) / first if first else 0
    if change >= 0.07:
        s, note = 1.0, f"цена снижена на {change * 100:.0f}%"
    elif change >= 0.03:
        s, note = 0.8, f"цена снижена на {change * 100:.0f}%"
    elif change < -0.01:
        s, note = 0.2, "цена повышалась"
    elif days_on_market > 45:
        s, note = 0.35, f"{int(days_on_market)} дн. в продаже без снижения цены"
    else:
        s, note = 0.5, "цена не менялась"
    if reposts:
        s -= 0.15
        note += f"; повторных публикаций: {reposts}"
    return _clamp(s), note


@dataclass
class ScoreResult:
    score: int
    label: str
    parts: dict
    warnings: list[str]


def label_for(score: int, cfg: ScoringConfig) -> str:
    t = cfg.thresholds
    if score >= t["great"]:
        return "very_interesting"
    if score >= t["good"]:
        return "worth_a_look"
    if score >= t["normal"]:
        return "normal"
    return "low"


LABEL_RU = {"very_interesting": "очень интересное предложение", "worth_a_look": "стоит изучить",
            "normal": "обычное предложение", "low": "низкий приоритет"}


def compute_score(listing: Any, cfg: ScoringConfig, liquidity: float | None,
                  history: list[tuple[int, datetime]], now: datetime | None = None) -> ScoreResult:
    now = now or utcnow()
    w = cfg.weights
    warnings: list[str] = []
    parts: dict[str, dict] = {}

    dev, conf = listing.deviation_pct, listing.confidence or 0.0
    if dev is None:
        price_s = 0.3
        warnings.append("рыночная оценка недоступна — недостаточно аналогов")
        conf_s = 0.0
    else:
        raw = _clamp((dev + 15) / 35)
        price_s = 0.3 + (raw - 0.3) * (0.4 + 0.6 * conf)  # при низкой достоверности тянем к нейтральному
        conf_s = conf
    parts["price"] = {"value": round(price_s, 2), "note": None if dev is None else f"{dev:+.1f}% к рынку"}
    parts["confidence"] = {"value": round(conf_s, 2), "note": None}

    if liquidity is None:
        liq_s = 0.5
        parts["liquidity"] = {"value": 0.5, "note": "данных о ликвидности недостаточно"}
    else:
        liq_s = liquidity
        parts["liquidity"] = {"value": round(liq_s, 2), "note": None}

    age = (now.year - listing.year) if listing.year else None
    if listing.mileage is None or not listing.year:
        mil_s = 0.4
        parts["mileage"] = {"value": mil_s, "note": "пробег неизвестен"}
        warnings.append("пробег не указан")
    else:
        expected = max(1, age) * cfg.km_per_year
        ratio = listing.mileage / expected
        mil_s = _clamp((1.8 - ratio) / 1.2)
        parts["mileage"] = {"value": round(mil_s, 2), "note": f"{listing.mileage:,} км при ожидаемых ~{expected:,}".replace(",", " ")}
        if ratio < 0.35 and age and age > 4:
            warnings.append("пробег подозрительно мал для возраста — проверьте историю")
    if age is None:
        age_s = 0.4
        parts["age"] = {"value": age_s, "note": "год неизвестен"}
    else:
        age_s = _clamp((26 - max(age, 0)) / 23)
        parts["age"] = {"value": round(age_s, 2), "note": f"{age} лет"}

    cond_s, text_warns, serious = analyze_text(f"{listing.title}. {listing.description}")
    warnings += text_warns
    parts["condition"] = {"value": round(cond_s, 2), "note": "по тексту описания; не заменяет осмотр"}

    first_seen = listing.first_seen_at or now
    dom = (now - (listing.posted_at or first_seen)).total_seconds() / 86400
    hist_s, hist_note = price_history_score(history, listing.price, dom, listing.repost_count or 0)
    parts["price_history"] = {"value": round(hist_s, 2), "note": hist_note}

    values = {"price": price_s, "liquidity": liq_s, "mileage": mil_s, "age": age_s, "condition": cond_s,
              "price_history": hist_s, "confidence": conf_s}
    total_w = sum(w.get(k, 0) for k in values) or 1
    raw_score = 100 * sum(w.get(k, 0) * v for k, v in values.items()) / total_w
    if listing.seller_type == "private":
        raw_score += cfg.private_bonus
        parts["private_bonus"] = {"value": cfg.private_bonus, "note": "частный продавец"}

    suspicious = dev is not None and dev >= cfg.suspicious_deviation
    if suspicious:
        warnings.append(f"⚠️ подозрительно дёшево: {dev:.0f}% ниже рынка — возможен скрытый дефект или мошенничество")
    score = int(round(_clamp(raw_score / 100) * 100))
    if (serious or suspicious) and score > cfg.risk_cap:
        score = cfg.risk_cap
        warnings.append(f"рейтинг ограничен {cfg.risk_cap} из-за признаков риска")
    if conf and conf < 0.4 and dev is not None:
        warnings.append("низкая достоверность рыночной оценки")
    return ScoreResult(score, label_for(score, cfg), parts, warnings)


def liquidity_estimate(prior: float | None, ages_days: list[float]) -> float | None:
    """prior — экспертная популярность модели; ages_days — возраст активных объявлений модели (дни).
    Данные влияют, только когда их ≥5. Возвращает None, если нет ни того ни другого."""
    data = None
    if len(ages_days) >= 5:
        ages = sorted(ages_days)
        med = ages[len(ages) // 2]
        data = _clamp(1 - (med - 5) / 55)
    if prior is None and data is None:
        return None
    if prior is None:
        return round(data, 2)
    if data is None:
        return round(prior * 0.9, 2)  # без данных — чуть консервативнее
    return round(0.6 * prior + 0.4 * data, 2)

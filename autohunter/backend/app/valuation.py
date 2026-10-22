"""Рыночная оценка: подбор аналогов с постепенным ослаблением критериев, очистка выбросов (MAD),
поправки на год/пробег, взвешенная медиана и доверительная оценка.

Важно: используются ЦЕНЫ ПРЕДЛОЖЕНИЯ, а не цены сделок. Фактическая цена продажи обычно ниже
(параметр asking_discount — оценка, не измеренная величина)."""
import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

from .dedupe import fingerprint


@dataclass
class ValuationParams:
    min_comps: int = 6          # достаточно для уверенной оценки
    min_fallback: int = 3       # минимум для любой оценки
    year_coef: float = 0.045    # потеря цены за год (по умолчанию; уточняется по данным, если их достаточно)
    mileage_coef_10k: float = 0.005  # потеря цены за каждые 10 тыс. км
    adj_cap: float = 0.35
    outlier_z: float = 3.5
    asking_discount: float = 0.05  # ожидаемая скидка «цена предложения → цена сделки» (оценка)


@dataclass
class Valuation:
    market_price: int | None
    low: int | None
    high: int | None
    confidence: float
    comps_count: int
    deviation_pct: float | None
    tier: str
    explain: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _wmedian(values: Sequence[float], weights: Sequence[float], q: float = 0.5) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(w for _, w in pairs)
    acc = 0.0
    for v, w in pairs:
        acc += w
        if acc >= q * total:
            return v
    return pairs[-1][0]


def _eq_known(a, b) -> bool:
    return a is None or b is None or a == b


def _near(a, b, tol) -> bool:
    return a is None or b is None or abs(a - b) <= tol


def _tiers(t: Any) -> list[tuple[str, float, Callable[[Any], bool]]]:
    def base(c, dy, tol_v, gen=True, fuel=True, trans=True, region=False):
        if c.brand != t.brand or c.model != t.model:
            return False
        if gen and t.generation and c.generation and c.generation != t.generation:
            return False
        if t.year and c.year and abs(c.year - t.year) > dy:
            return False
        if fuel and not _eq_known(c.fuel, t.fuel):
            return False
        if trans and not _eq_known(c.transmission, t.transmission):
            return False
        if tol_v is not None and not _near(c.engine_volume, t.engine_volume, tol_v):
            return False
        if region and t.region and c.region != t.region:
            return False
        return True

    return [
        ("точные аналоги в регионе", 1.0, lambda c: base(c, 1, 0.3, region=True)),
        ("точные аналоги по стране", 0.9, lambda c: base(c, 1, 0.3)),
        ("близкие аналоги (год ±2, объём ±0.5)", 0.75, lambda c: base(c, 2, 0.5)),
        ("модель, год ±3, тот же тип топлива", 0.55, lambda c: base(c, 3, None, gen=False, trans=False)),
        ("модель, год ±5", 0.4, lambda c: base(c, 5, None, gen=False, fuel=False, trans=False)),
    ]


def _theil_sen_year_slope(items: list[tuple[int, float]]) -> float | None:
    """Робастный наклон ln(цена) по году по парным наклонам."""
    slopes = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            dy = items[j][0] - items[i][0]
            if dy:
                slopes.append((items[j][1] - items[i][1]) / dy)
    if len(slopes) < 6 or len({y for y, _ in items}) < 3:
        return None
    return statistics.median(slopes)


def _clean(prices_adj: list[float], z_thr: float) -> list[bool]:
    """Маска «оставить» по модифицированному z-score на ln(цены)."""
    logs = [math.log(p) for p in prices_adj]
    if len(logs) < 4:
        return [True] * len(logs)
    med = statistics.median(logs)
    mad = statistics.median([abs(x - med) for x in logs])
    keep = []
    for x in logs:
        if mad < 1e-9:
            keep.append(abs(x - med) < 0.35)
        else:
            keep.append(abs(0.6745 * (x - med) / mad) <= z_thr)
    return keep


def estimate(target: Any, pool: Sequence[Any], params: ValuationParams | None = None) -> Valuation:
    p = params or ValuationParams()
    tid = getattr(target, "id", None)
    cand_all = [c for c in pool if getattr(c, "id", None) != tid and getattr(c, "price", None)
                and not getattr(c, "dup_of_id", None)]
    notes: list[str] = []
    best: tuple | None = None

    for idx, (label, tier_factor, pred) in enumerate(_tiers(target)):
        matched = [c for c in cand_all if pred(c)]
        if len(matched) < p.min_fallback:
            continue
        # схлопываем дубли внутри набора аналогов
        seen: dict[str, Any] = {}
        uniq = []
        for c in matched:
            fp = fingerprint(c)
            if fp and fp in seen:
                continue
            if fp:
                seen[fp] = c
            uniq.append(c)
        dups_removed = len(matched) - len(uniq)

        slope = p.year_coef
        slope_src = "по умолчанию"
        yrs = [(c.year, math.log(c.price)) for c in uniq if c.year]
        if len(yrs) >= 10:
            s = _theil_sen_year_slope(yrs)
            if s is not None and 0.02 <= s <= 0.10:
                slope, slope_src = s, "по данным выборки (Тейл–Сен)"

        adj = []
        for c in uniq:
            f = 1.0
            if target.year and c.year:
                f *= math.exp(max(-p.adj_cap, min(p.adj_cap, slope * (target.year - c.year))))
            if target.mileage is not None and c.mileage is not None:
                f *= 1 + max(-p.adj_cap, min(p.adj_cap, p.mileage_coef_10k * (c.mileage - target.mileage) / 10_000))
            adj.append(c.price * f)

        keep = _clean(adj, p.outlier_z)
        used = [(c, a) for c, a, k in zip(uniq, adj, keep) if k]
        outliers = len(uniq) - len(used)
        if len(used) < p.min_fallback:
            continue
        rec = (idx, label, tier_factor, used, outliers, dups_removed, slope, slope_src)
        if len(used) >= p.min_comps:
            best = rec
            break
        if best is None or len(used) > len(best[3]):
            best = rec

    if best is None:
        return Valuation(None, None, None, 0.0, 0, None, "недостаточно данных",
                         {"reason": "не найдено достаточно сопоставимых объявлений", "notes": notes})

    idx, label, tier_factor, used, outliers, dups_removed, slope, slope_src = best
    weights = []
    for c, _ in used:
        d = 1.0
        if target.year and c.year:
            d += 0.5 * abs(target.year - c.year)
        if target.mileage is not None and c.mileage is not None:
            d += abs(target.mileage - c.mileage) / 50_000
        if target.region and c.region != target.region:
            d += 0.3
        if target.transmission and c.transmission != target.transmission:
            d += 0.3
        if target.drive and c.drive and c.drive != target.drive:
            d += 0.3
        weights.append(1 / d)
    vals = [a for _, a in used]
    market = _wmedian(vals, weights)
    low, high = _wmedian(vals, weights, 0.25), _wmedian(vals, weights, 0.75)
    n = len(used)

    known = sum(x is not None for x in (target.year, target.mileage, target.engine_volume, target.fuel,
                                        target.transmission, target.generation))
    c_n = 1 - math.exp(-n / 8)
    rel = (high - low) / market if market else 1
    c_disp = max(0.1, min(1.0, 1 - rel / 0.5))
    c_attr = 0.5 + 0.5 * known / 6
    conf = (c_n ** 0.4) * (c_disp ** 0.3) * (tier_factor ** 0.2) * (c_attr ** 0.1)
    if n < p.min_comps:
        conf *= 0.7
        notes.append(f"аналогов меньше {p.min_comps} — оценка ориентировочная")
    if target.mileage is None:
        notes.append("пробег неизвестен — поправка на пробег не применялась")
    if idx >= 3:
        notes.append("критерии подбора сильно расширены")
    conf = round(max(0.0, min(1.0, conf)), 2)

    deviation = round((market - target.price) / market * 100, 1) if getattr(target, "price", None) else None
    explain = {
        "tier": label, "tier_index": idx, "comps_used": n, "outliers_removed": outliers,
        "duplicates_removed": dups_removed,
        "year_slope": round(slope, 4), "year_slope_source": slope_src,
        "mileage_coef_per_10k_km": p.mileage_coef_10k,
        "expected_sale_price": int(market * (1 - p.asking_discount)),
        "asking_discount_assumed": p.asking_discount,
        "confidence_parts": {"n": round(c_n, 2), "dispersion": round(c_disp, 2), "tier": tier_factor,
                             "attributes": round(c_attr, 2)},
        "notes": notes,
        "disclaimer": "Оценка построена по ценам предложений, а не фактическим ценам сделок.",
        "sample": [{"id": getattr(c, "id", None), "price": c.price, "adjusted": int(a), "year": c.year,
                    "mileage": c.mileage} for c, a in sorted(used, key=lambda x: x[1])[:12]],
    }
    return Valuation(int(market), int(low), int(high), conf, n, deviation, label, explain)

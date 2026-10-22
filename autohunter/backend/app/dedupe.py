"""Поиск дублей и повторных публикаций (чистые функции; запросы к БД — в pipeline)."""
import hashlib
from typing import Any


def _g(o: Any, k: str):
    return getattr(o, k, None)


def fingerprint(c: Any) -> str | None:
    """Ключ для схлопывания одинаковых машин внутри набора аналогов. None — схлопывать нельзя."""
    vin = _g(c, "vin")
    if vin and len(vin) >= 11:
        return "vin:" + vin
    km = _g(c, "mileage")
    if km is None or not _g(c, "year"):
        return None
    raw = "|".join(str(x) for x in (_g(c, "brand"), _g(c, "model"), _g(c, "year"), _g(c, "engine_volume"),
                                    _g(c, "transmission"), round(km / 500), _g(c, "region")))
    return "fp:" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def is_duplicate(a: Any, b: Any) -> str | None:
    """Возвращает причину, если a и b — вероятно одна и та же машина; иначе None."""
    va, vb = _g(a, "vin"), _g(b, "vin")
    if va and vb and len(va) >= 11:
        return "vin" if va == vb else None
    for f in ("brand", "model", "year"):
        if _g(a, f) != _g(b, f):
            return None
    for f in ("engine_volume", "transmission", "fuel", "drive"):
        x, y = _g(a, f), _g(b, f)
        if x is not None and y is not None and x != y:
            return None
    ka, kb = _g(a, "mileage"), _g(b, "mileage")
    if ka is None or kb is None:
        return None
    if abs(ka - kb) > max(500, 0.015 * max(ka, kb)):
        return None
    pa, pb = _g(a, "price"), _g(b, "price")
    if not pa or not pb or abs(pa - pb) / max(pa, pb) > 0.15:
        return None
    ra, rb = _g(a, "region"), _g(b, "region")
    if ra and rb and ra != rb:
        return None
    sa, sb = _g(a, "seller_key"), _g(b, "seller_key")
    if sa and sb and sa == sb:
        return "seller+attrs"
    ca, cb = _g(a, "city"), _g(b, "city")
    if ca and cb and ca != cb:
        return None
    return "attrs"

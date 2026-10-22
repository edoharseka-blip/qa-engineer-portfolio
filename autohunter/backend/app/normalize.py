"""Нормализация сырых объявлений к единому виду + валидация."""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import catalog
from .schemas import RawListing
from .timeutil import to_naive_utc, utcnow


class ValidationError(ValueError):
    pass


@dataclass
class Normalized:
    source: str
    source_id: str
    url: str
    title: str
    description: str
    brand: str
    model: str | None
    generation: str | None = None
    restyling: bool = False
    year: int | None = None
    engine_volume: float | None = None
    power_hp: int | None = None
    fuel: str | None = None
    transmission: str | None = None
    drive: str | None = None
    body: str | None = None
    mileage: int | None = None
    vin: str | None = None
    trim: str | None = None
    price: int = 0
    region: str | None = None
    city: str | None = None
    seller_type: str | None = None
    seller_key: str | None = None
    photos: list[str] = field(default_factory=list)
    posted_at: datetime | None = None
    is_demo: bool = False
    content_hash: str = ""


MIN_PRICE, MAX_PRICE = 30_000, 100_000_000


def detect_brand(text: str) -> str | None:
    t = text.lower()
    for brand, aliases in catalog.BRAND_ALIASES.items():
        for a in sorted(aliases, key=len, reverse=True):
            if re.search(rf"(?<![\w-]){re.escape(a)}(?![\w-])", t):
                return brand
    return None


def detect_model(brand: str, text: str) -> str | None:
    for pat, fmt in catalog.MODEL_PATTERNS.get(brand, []):
        m = pat.search(text)
        if m:
            g = m.group(1).upper()
            return fmt.format(g)
    return None


def canonical_model(brand: str, model: str | None) -> str | None:
    """Приводит структурное поле модели от источника к каноническому имени."""
    if not model:
        return None
    m = detect_model(brand, model)
    if m:
        return m
    known = {mm for (b, mm) in catalog.GENERATIONS if b == brand}
    low = model.strip().lower()
    for k in known:
        if k.lower() == low:
            return k
    return model.strip()


def detect_generation(brand: str, model: str | None, year: int | None, text: str) -> tuple[str | None, bool]:
    gens = catalog.GENERATIONS.get((brand, model or ""), [])
    if not gens:
        return None, False
    low = text.lower()
    candidates = gens
    tokens = [g for g in gens if re.search(rf"(?<![\w]){re.escape(g[0].split()[0].lower())}(?![\w])", low)]
    if tokens:
        first = tokens[0][0].split()[0]
        candidates = [g for g in gens if g[0].split()[0] == first]
    chosen = None
    if year:
        inside = [g for g in candidates if g[1] <= year <= g[2]]
        if inside:
            chosen = max(inside, key=lambda g: g[1])
        else:
            chosen = min(candidates, key=lambda g: min(abs(year - g[1]), abs(year - g[2])))
            if min(abs(year - chosen[1]), abs(year - chosen[2])) > 2:
                chosen = None
    elif len(candidates) == 1 or tokens:
        chosen = candidates[0]
    if not chosen:
        return None, False
    resty = chosen[3] or bool(re.search(r"рестайл|restyl|\blci\b", low))
    return chosen[0], resty


def _lookup(mapping: dict[str, str], value: str | None, text: str = "") -> str | None:
    if value:
        v = value.strip().lower()
        if v in mapping:
            return mapping[v]
        for k, res in mapping.items():
            if len(k) > 3 and k in v:
                return res
    if text:
        low = text.lower()
        for k, res in mapping.items():
            if re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", low):
                return res
    return None


def normalize_region(region: str | None, city: str | None) -> tuple[str | None, str | None]:
    city_c = city.strip() if city else None
    if region:
        low = region.lower()
        for r in catalog.REGIONS:
            if r.lower() == low or r.lower().split()[0].rstrip("ая") in low and r.lower().split()[-1] in low:
                return r, city_c
        if low.strip() in catalog.CITY_REGION:
            return catalog.CITY_REGION[low.strip()], city_c or region.strip()
    if city_c and city_c.lower() in catalog.CITY_REGION:
        return catalog.CITY_REGION[city_c.lower()], city_c
    return (region.strip() if region else None), city_c


def normalize_seller(v: str | None) -> str | None:
    if not v:
        return None
    low = v.lower()
    if any(k in low for k in ("private", "част", "собственник", "owner")):
        return "private"
    if any(k in low for k in ("dealer", "дилер", "салон", "компан", "company", "автосалон")):
        return "dealer"
    return None


_YEAR = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
_VOL = re.compile(r"(?<![\d.])([1-6][.,]\d)\s?(?:л\b|l\b|i\b|d\b|t\b|tdi|tfsi|\s|,|$)", re.I)
_HP = re.compile(r"(\d{2,3})\s?(?:л\.?\s?с|hp|лс)", re.I)
_KM = re.compile(r"(\d[\d\s ]{1,8}\d)\s?(?:км|km)\b", re.I)
_KKM = re.compile(r"(\d{2,3})\s?(?:тыс\.?\s?км|т\.?\s?км|000\s?км)", re.I)


def _text_fields(text: str) -> dict:
    out: dict = {}
    if m := _YEAR.search(text):
        out["year"] = int(m.group(1))
    if m := _VOL.search(text):
        out["engine_volume"] = float(m.group(1).replace(",", "."))
    if m := _HP.search(text):
        out["power_hp"] = int(m.group(1))
    if m := _KM.search(text):
        out["mileage"] = int(re.sub(r"\D", "", m.group(1)))
    elif m := _KKM.search(text):
        out["mileage"] = int(m.group(1)) * 1000
    return out


def _bmw_engine_from_name(text: str) -> tuple[float | None, str | None]:
    m = re.search(r"(?<![\w.])([135])([1-3]\d)(i|d)\b", text, re.I)
    if not m:
        return None, None
    disp = int(m.group(2)) / 10
    if not 1.5 <= disp <= 3.5:
        return None, None
    return disp, ("diesel" if m.group(3).lower() == "d" else "petrol")


def normalize(raw: RawListing) -> Normalized:
    if not raw.source_id or not raw.url:
        raise ValidationError("нет source_id или url")
    if raw.price is None or not (MIN_PRICE <= raw.price <= MAX_PRICE):
        raise ValidationError(f"некорректная цена: {raw.price}")
    text = f"{raw.title}. {raw.description}"
    brand = detect_brand(raw.brand or "") or detect_brand(raw.title)
    if not brand:
        raise ValidationError("марка не поддерживается/не определена")
    model = canonical_model(brand, raw.model) or detect_model(brand, raw.title) or detect_model(brand, text)
    tf = _text_fields(raw.title) | {k: v for k, v in _text_fields(raw.description).items() if k not in _text_fields(raw.title)}
    year = raw.year or tf.get("year")
    if year is not None and not (1980 <= year <= utcnow().year + 1):
        raise ValidationError(f"некорректный год: {year}")
    mileage = raw.mileage if raw.mileage is not None else tf.get("mileage")
    if mileage is not None and not (0 <= mileage <= 2_000_000):
        raise ValidationError(f"некорректный пробег: {mileage}")
    volume = raw.engine_volume or tf.get("engine_volume")
    fuel = _lookup(catalog.FUELS, raw.fuel, text)
    if brand == "BMW" and not volume:
        v2, f2 = _bmw_engine_from_name(raw.title)
        volume = v2
        fuel = fuel or f2
    if volume is not None and not (0.6 <= volume <= 8.5):
        volume = None
    gen, resty = detect_generation(brand, model, year, text)
    region, city = normalize_region(raw.region, raw.city)
    photos = [p for p in raw.photos if isinstance(p, str) and p.startswith(("http://", "https://"))][:10]
    n = Normalized(
        source=raw.source, source_id=str(raw.source_id), url=raw.url, title=raw.title.strip()[:300],
        description=raw.description.strip(), brand=brand, model=model, generation=gen, restyling=resty,
        year=year, engine_volume=volume, power_hp=raw.power_hp or tf.get("power_hp"), fuel=fuel,
        transmission=_lookup(catalog.TRANSMISSIONS, raw.transmission, text),
        drive=_lookup(catalog.DRIVES, raw.drive, text),
        body=_lookup(catalog.BODIES, raw.body, text), mileage=mileage,
        vin=(raw.vin or None) and raw.vin.upper(), trim=raw.trim, price=int(raw.price), region=region, city=city,
        seller_type=normalize_seller(raw.seller_type), seller_key=raw.seller_key, photos=photos,
        posted_at=to_naive_utc(raw.posted_at), is_demo=raw.is_demo,
    )
    n.content_hash = content_hash(n)
    return n


def content_hash(n: Normalized) -> str:
    key = "|".join(str(x) for x in (n.price, n.title, n.mileage, n.year, n.description[:200], len(n.photos)))
    return hashlib.sha1(key.encode()).hexdigest()

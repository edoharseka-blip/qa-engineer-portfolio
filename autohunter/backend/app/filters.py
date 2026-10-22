"""Единая реализация фильтров: SQL (для ленты) и Python (для профилей/уведомлений). Тесты проверяют их согласие."""
from sqlalchemy import Select, and_, or_

from .models import Listing
from .schemas import ListingFilter


def conditions(f: ListingFilter) -> list:
    c = []
    L = Listing
    if not f.include_hidden:
        c.append(L.hidden.is_(False))
    if not f.include_duplicates:
        c.append(L.dup_of_id.is_(None))
    if not f.include_inactive:
        c.append(L.is_active.is_(True))
    if f.only_favorites:
        c.append(L.favorite.is_(True))
    for col, vals in ((L.brand, f.brands), (L.model, f.models), (L.generation, f.generations), (L.fuel, f.fuels),
                      (L.transmission, f.transmissions), (L.drive, f.drives), (L.body, f.bodies),
                      (L.seller_type, f.seller_types), (L.source, f.sources)):
        if vals:
            c.append(col.in_(vals))
    for col, lo, hi in ((L.year, f.year_min, f.year_max), (L.price, f.price_min, f.price_max),
                        (L.mileage, f.mileage_min, f.mileage_max),
                        (L.engine_volume, f.engine_volume_min, f.engine_volume_max)):
        if lo is not None:
            c.append(col >= lo)
        if hi is not None:
            c.append(col <= hi)
    if f.regions and f.cities:
        c.append(or_(L.region.in_(f.regions), L.city.in_(f.cities)))
    elif f.regions:
        c.append(L.region.in_(f.regions))
    elif f.cities:
        c.append(L.city.in_(f.cities))
    if f.deviation_min is not None:
        c.append(L.deviation_pct >= f.deviation_min)
    if f.score_min is not None:
        c.append(L.score >= f.score_min)
    if f.posted_after is not None:
        c.append(or_(L.posted_at >= f.posted_after, and_(L.posted_at.is_(None), L.first_seen_at >= f.posted_after)))
    if f.q:
        c.append(L.search_text.contains(f.q.lower(), autoescape=True))
    return c


def apply_filter(stmt: Select, f: ListingFilter) -> Select:
    return stmt.where(*conditions(f))


def matches(l, f: ListingFilter) -> bool:
    if l.hidden and not f.include_hidden:
        return False
    if l.dup_of_id is not None and not f.include_duplicates:
        return False
    if not l.is_active and not f.include_inactive:
        return False
    if f.only_favorites and not l.favorite:
        return False
    for attr, vals in (("brand", f.brands), ("model", f.models), ("generation", f.generations), ("fuel", f.fuels),
                       ("transmission", f.transmissions), ("drive", f.drives), ("body", f.bodies),
                       ("seller_type", f.seller_types), ("source", f.sources)):
        if vals and getattr(l, attr) not in vals:
            return False
    for attr, lo, hi in (("year", f.year_min, f.year_max), ("price", f.price_min, f.price_max),
                         ("mileage", f.mileage_min, f.mileage_max),
                         ("engine_volume", f.engine_volume_min, f.engine_volume_max)):
        v = getattr(l, attr)
        if lo is not None and (v is None or v < lo):
            return False
        if hi is not None and (v is None or v > hi):
            return False
    if f.regions and f.cities:
        if l.region not in f.regions and l.city not in f.cities:
            return False
    elif f.regions and l.region not in f.regions:
        return False
    elif f.cities and l.city not in f.cities:
        return False
    if f.deviation_min is not None and (l.deviation_pct is None or l.deviation_pct < f.deviation_min):
        return False
    if f.score_min is not None and (l.score is None or l.score < f.score_min):
        return False
    if f.posted_after is not None:
        t = l.posted_at or l.first_seen_at
        if t is None or t < f.posted_after:
            return False
    if f.q:
        if f.q.lower() not in (l.search_text or f"{l.title} {l.description}".lower()):
            return False
    return True

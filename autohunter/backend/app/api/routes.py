import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import catalog
from ..filters import apply_filter
from ..models import KV, Listing, Notification, PriceHistory, SearchProfile, SourceState
from ..notifier import LogTransport, format_listing, listing_buttons
from ..schemas import ListingFilter
from ..scoring import LABEL_RU, ScoringConfig
from ..store import get_scoring_config, get_valuation_params, kv_get, kv_set
from ..timeutil import utcnow
from ..valuation import ValuationParams
from .auth import create_token, require_auth

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


# ---------- сериализация ----------
def iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def listing_dict(l: Listing, detail: bool = False) -> dict:
    d = {
        "id": l.id, "source": l.source, "url": l.url, "title": l.title, "brand": l.brand, "model": l.model,
        "generation": l.generation, "restyling": l.restyling, "year": l.year, "engine_volume": l.engine_volume,
        "power_hp": l.power_hp, "fuel": l.fuel, "transmission": l.transmission, "drive": l.drive, "body": l.body,
        "mileage": l.mileage, "price": l.price, "price_initial": l.price_initial, "region": l.region,
        "city": l.city, "seller_type": l.seller_type, "photos": l.photos or [], "posted_at": iso(l.posted_at),
        "first_seen_at": iso(l.first_seen_at), "notified_at": iso(l.notified_at), "market_price": l.market_price,
        "market_low": l.market_low, "market_high": l.market_high, "deviation_pct": l.deviation_pct,
        "confidence": l.confidence, "comps_count": l.comps_count, "score": l.score, "score_label": l.score_label,
        "score_label_ru": LABEL_RU.get(l.score_label or ""), "warnings": l.warnings or [], "liquidity": l.liquidity,
        "favorite": l.favorite, "hidden": l.hidden, "repost_count": l.repost_count, "is_demo": l.is_demo,
        "is_active": l.is_active, "dup_of_id": l.dup_of_id,
    }
    if detail:
        d.update(description=l.description, vin=l.vin, valuation=l.valuation, score_parts=l.score_parts,
                 last_seen_at=iso(l.last_seen_at),
                 days_on_market=round(((utcnow()) - (l.posted_at or l.first_seen_at)).total_seconds() / 86400, 1))
    return d


async def db_session(request: Request):
    async with request.app.state.db.session() as s:
        yield s


# ---------- auth ----------
class LoginIn(BaseModel):
    password: str


@public.post("/auth/login")
async def login(body: LoginIn, request: Request):
    st = request.app.state
    ip = request.client.host if request.client else "?"
    if not st.login_limiter.allow(ip):
        raise HTTPException(429, "Слишком много попыток входа")
    import hmac
    if not hmac.compare_digest(body.password.encode(), st.settings.auth_password.encode()):
        raise HTTPException(401, "Неверный пароль")
    return {"token": create_token(st.settings.auth_secret, st.settings.auth_token_ttl_hours)}


@public.get("/healthz")
async def healthz(request: Request):
    async with request.app.state.db.session() as s:
        await s.execute(select(1))
    return {"status": "ok"}


# ---------- лента ----------
class SearchIn(BaseModel):
    filter: ListingFilter = Field(default_factory=ListingFilter)
    sort: str = "new"
    limit: int = Field(30, ge=1, le=200)
    offset: int = Field(0, ge=0)


SORTS = {
    "new": (Listing.first_seen_at.desc(), Listing.id.desc()),
    "score": (Listing.score.desc().nullslast(), Listing.id.desc()),
    "deviation": (Listing.deviation_pct.desc().nullslast(), Listing.id.desc()),
    "price_asc": (Listing.price.asc(), Listing.id.desc()),
    "price_desc": (Listing.price.desc(), Listing.id.desc()),
    "posted": (Listing.posted_at.desc().nullslast(), Listing.id.desc()),
}


@router.post("/listings/search")
async def search(body: SearchIn, s=Depends(db_session)):
    if body.sort not in SORTS:
        raise HTTPException(422, f"sort должен быть одним из {list(SORTS)}")
    q = apply_filter(select(Listing), body.filter)
    total = (await s.execute(apply_filter(select(func.count(Listing.id)), body.filter))).scalar_one()
    rows = (await s.execute(q.order_by(*SORTS[body.sort]).limit(body.limit).offset(body.offset))).scalars().all()
    max_id = (await s.execute(select(func.max(Listing.id)))).scalar_one()
    return {"total": total, "max_id": max_id, "items": [listing_dict(l) for l in rows]}


@router.get("/listings/{lid}")
async def get_listing(lid: int, s=Depends(db_session)):
    l = await s.get(Listing, lid)
    if not l:
        raise HTTPException(404, "Не найдено")
    hist = (await s.execute(select(PriceHistory).where(PriceHistory.listing_id == lid)
                            .order_by(PriceHistory.seen_at))).scalars().all()
    d = listing_dict(l, detail=True)
    d["price_history"] = [{"price": h.price, "at": iso(h.seen_at)} for h in hist]
    ids = [x["id"] for x in (l.valuation or {}).get("sample", []) if x.get("id")]
    comps = (await s.execute(select(Listing).where(Listing.id.in_(ids)))).scalars().all() if ids else []
    d["comparables"] = [listing_dict(c) for c in sorted(comps, key=lambda c: c.price)]
    dups = (await s.execute(select(Listing).where(Listing.dup_of_id == lid))).scalars().all()
    d["duplicates"] = [{"id": x.id, "source": x.source, "url": x.url, "price": x.price} for x in dups]
    return d


@router.post("/listings/{lid}/favorite")
async def favorite(lid: int, s=Depends(db_session)):
    l = await s.get(Listing, lid)
    if not l:
        raise HTTPException(404, "Не найдено")
    l.favorite = not l.favorite
    await s.commit()
    return {"favorite": l.favorite}


@router.post("/listings/{lid}/hide")
async def hide(lid: int, s=Depends(db_session)):
    l = await s.get(Listing, lid)
    if not l:
        raise HTTPException(404, "Не найдено")
    l.hidden = not l.hidden
    await s.commit()
    return {"hidden": l.hidden}


# ---------- профили ----------
class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    filters: ListingFilter = Field(default_factory=ListingFilter)
    notify: bool = True
    notify_min_score: int = Field(70, ge=0, le=100)
    notify_min_deviation: float = 10.0
    active: bool = True


def profile_dict(p: SearchProfile) -> dict:
    return {"id": p.id, "name": p.name, "filters": p.filters, "notify": p.notify,
            "notify_min_score": p.notify_min_score, "notify_min_deviation": p.notify_min_deviation,
            "active": p.active}


@router.get("/profiles")
async def list_profiles(s=Depends(db_session)):
    return [profile_dict(p) for p in (await s.execute(select(SearchProfile).order_by(SearchProfile.id))).scalars()]


@router.post("/profiles")
async def create_profile(body: ProfileIn, s=Depends(db_session)):
    if (await s.execute(select(SearchProfile.id).where(SearchProfile.name == body.name))).first():
        raise HTTPException(409, "Профиль с таким именем уже есть")
    p = SearchProfile(name=body.name, filters=body.filters.model_dump(mode="json", exclude_defaults=True),
                      notify=body.notify, notify_min_score=body.notify_min_score,
                      notify_min_deviation=body.notify_min_deviation, active=body.active)
    s.add(p)
    await s.commit()
    return profile_dict(p)


@router.put("/profiles/{pid}")
async def update_profile(pid: int, body: ProfileIn, s=Depends(db_session)):
    p = await s.get(SearchProfile, pid)
    if not p:
        raise HTTPException(404, "Не найдено")
    p.name, p.notify, p.active = body.name, body.notify, body.active
    p.filters = body.filters.model_dump(mode="json", exclude_defaults=True)
    p.notify_min_score, p.notify_min_deviation = body.notify_min_score, body.notify_min_deviation
    await s.commit()
    return profile_dict(p)


@router.delete("/profiles/{pid}")
async def delete_profile(pid: int, s=Depends(db_session)):
    p = await s.get(SearchProfile, pid)
    if not p:
        raise HTTPException(404, "Не найдено")
    await s.delete(p)
    await s.commit()
    return {"ok": True}


# ---------- метаданные ----------
@router.get("/meta")
async def meta(request: Request, s=Depends(db_session)):
    rows = (await s.execute(select(Listing.brand, Listing.model, Listing.generation).distinct())).all()
    brands = sorted({r[0] for r in rows if r[0]})
    models = defaultdict(set)
    gens = defaultdict(set)
    for b, m, g in rows:
        if b and m:
            models[b].add(m)
            if g:
                gens[m].add(g)
    regions = sorted({r[0] for r in (await s.execute(select(Listing.region).distinct())).all() if r[0]})
    st = request.app.state
    return {"brands": brands, "models": {k: sorted(v) for k, v in models.items()},
            "generations": {k: sorted(v) for k, v in gens.items()}, "regions": regions or catalog.REGIONS,
            "all_regions": catalog.REGIONS, "demo_mode": any(a.is_demo for a in st.adapters),
            "sources": [a.name for a in st.adapters]}


# ---------- аналитика ----------
def _median(v):
    return int(statistics.median(v)) if v else None


@router.post("/analytics")
async def analytics(flt: ListingFilter, s=Depends(db_session)):
    flt = flt.model_copy(update={"include_hidden": True})
    rows = (await s.execute(apply_filter(select(Listing), flt).limit(20000))).scalars().all()
    now = utcnow()
    prices = sorted(l.price for l in rows)
    out: dict = {"count": len(rows), "median_price": _median(prices),
                 "p25": int(prices[len(prices) // 4]) if prices else None,
                 "p75": int(prices[len(prices) * 3 // 4]) if prices else None}
    if prices:
        lo, hi = prices[0], prices[-1]
        n_bins = 12
        step = max(1, (hi - lo) / n_bins)
        bins = Counter(min(n_bins - 1, int((p - lo) / step)) for p in prices)
        out["histogram"] = [{"from": int(lo + i * step), "to": int(lo + (i + 1) * step), "count": bins.get(i, 0)}
                            for i in range(n_bins)]
    ages = [(now - (l.posted_at or l.first_seen_at)).total_seconds() / 86400 for l in rows]
    edges = [(1, "<1 дня"), (3, "1–3"), (7, "3–7"), (14, "7–14"), (30, "14–30"), (1e9, "30+")]
    out["age_distribution"] = [{"bucket": lbl, "count": sum(1 for a in ages if (edges[i - 1][0] if i else 0) <= a < e)}
                               for i, (e, lbl) in enumerate(edges)]
    out["median_age_days"] = round(statistics.median(ages), 1) if ages else None

    def group(keyf, label):
        g = defaultdict(list)
        for l in rows:
            k = keyf(l)
            if k:
                g[k].append(l)
        return sorted(({label: k, "count": len(v), "median_price": _median([x.price for x in v]),
                        "median_mileage": _median([x.mileage for x in v if x.mileage is not None]),
                        "median_year": _median([x.year for x in v if x.year])}
                       for k, v in g.items()), key=lambda r: -r["count"])[:20]

    out["by_generation"] = group(lambda l: f"{l.brand} {l.model} {l.generation}" if l.generation else None, "name")
    out["by_engine"] = group(lambda l: (f"{l.engine_volume:.1f} {l.fuel}" if l.engine_volume and l.fuel else None), "name")
    out["by_region"] = group(lambda l: l.region, "name")
    liq = defaultdict(list)
    for l in rows:
        if l.model:
            liq[f"{l.brand} {l.model}"].append(l)
    out["liquidity"] = sorted(({"name": k, "count": len(v),
                                "liquidity": round(statistics.fmean(x.liquidity for x in v if x.liquidity is not None), 2)
                                if any(x.liquidity is not None for x in v) else None,
                                "median_age_days": round(statistics.median(
                                    [(now - (x.posted_at or x.first_seen_at)).total_seconds() / 86400 for x in v]), 1)}
                               for k, v in liq.items()), key=lambda r: -(r["liquidity"] or 0))[:20]
    day = defaultdict(list)
    for l in rows:
        d = (l.posted_at or l.first_seen_at).date().isoformat()
        day[d].append(l.price)
    out["trend"] = [{"day": d, "median_price": _median(v), "count": len(v)} for d, v in sorted(day.items())][-30:]
    out["note"] = "Показатели рассчитаны по ценам предложений в текущей выборке; это не цены сделок."
    return out


# ---------- мониторинг ----------
def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


@router.get("/monitoring")
async def monitoring(request: Request, s=Depends(db_session)):
    st = request.app.state
    now = utcnow()
    states = {x.source: x for x in (await s.execute(select(SourceState))).scalars()}
    since = now - timedelta(hours=24)
    rows = (await s.execute(select(Listing.source, Listing.posted_at, Listing.first_seen_at, Listing.notified_at,
                                   Listing.is_demo).where(Listing.first_seen_at >= since, Listing.is_backfill.is_(False))
                            .order_by(Listing.id.desc()).limit(10000))).all()
    lat: dict[str, list[float]] = defaultdict(list)
    nlat: list[float] = []
    for src, posted, seen, notified, _demo in rows:
        if posted:
            lat[src].append(max(0.0, (seen - posted).total_seconds()))
        if notified:
            nlat.append(max(0.0, (notified - seen).total_seconds()))
    counts = dict((await s.execute(select(Listing.source, func.count(Listing.id)).group_by(Listing.source))).all())
    sources = []
    for a in st.adapters:
        x = states.get(a.name)
        v = sorted(lat.get(a.name, []))
        sources.append({
            "name": a.name, "title": a.title, "configured": a.configured(), "is_demo": a.is_demo,
            "note": a.status_note, "listings": counts.get(a.name, 0),
            "last_success_at": iso(x.last_success_at) if x else None, "last_error": x.last_error if x else None,
            "last_error_at": iso(x.last_error_at) if x else None,
            "consecutive_failures": x.consecutive_failures if x else 0, "processed_total": x.processed_total if x else 0,
            "new_total": x.new_total if x else 0, "error_total": x.error_total if x else 0,
            "detection_latency_s": {"avg": round(sum(v) / len(v), 1) if v else None, "p95": round(_pct(v, 0.95), 1) if v else None,
                                    "samples": len(v),
                                    "synthetic": a.is_demo},
        })
    nl = sorted(nlat)
    sent = (await s.execute(select(func.count(Notification.id)).where(Notification.status == "sent"))).scalar_one()
    bot = st.bot
    return {
        "sources": sources, "total_listings": sum(counts.values()),
        "notification_latency_s": {"avg": round(sum(nl) / len(nl), 1) if nl else None, "p95": round(_pct(nl, 0.95), 1) if nl else None, "samples": len(nl)},
        "telegram": {"mode": "telegram" if bot else "stub", "running": bool(bot and bot.task and not bot.task.done()),
                     "last_error": bot.last_error if bot else None, "sent_total": sent,
                     "chats": len(await st.notifier.chat_ids(s)), "paused": bool(await kv_get(s, "notifications_paused", False))},
        "latency_note": "Задержка = время обнаружения − время публикации по данным источника. "
                        "Первичная загрузка (backfill) не учитывается. Для демо-источника время публикации синтетическое.",
        "server_time": iso(now),
    }


# ---------- настройки ----------
@router.get("/settings")
async def get_settings_(s=Depends(db_session)):
    return {"scoring": (await get_scoring_config(s)).to_dict(),
            "valuation": (await get_valuation_params(s)).__dict__,
            "notifications_paused": bool(await kv_get(s, "notifications_paused", False))}


class SettingsIn(BaseModel):
    scoring: dict | None = None
    valuation: dict | None = None
    notifications_paused: bool | None = None


@router.put("/settings")
async def put_settings(body: SettingsIn, s=Depends(db_session)):
    if body.scoring is not None:
        cfg = ScoringConfig.from_dict(body.scoring)
        if any(w < 0 for w in cfg.weights.values()) or sum(cfg.weights.values()) <= 0:
            raise HTTPException(422, "Веса должны быть неотрицательными и не нулевыми в сумме")
        t = cfg.thresholds
        if not (t["normal"] < t["good"] < t["great"] <= 100):
            raise HTTPException(422, "Пороги должны возрастать: normal < good < great ≤ 100")
        await kv_set(s, "scoring", cfg.to_dict())
    if body.valuation is not None:
        allowed = ValuationParams().__dict__
        bad = [k for k in body.valuation if k not in allowed]
        if bad:
            raise HTTPException(422, f"Неизвестные параметры: {bad}")
        await kv_set(s, "valuation", body.valuation)
    if body.notifications_paused is not None:
        await kv_set(s, "notifications_paused", body.notifications_paused)
    await s.commit()
    return await get_settings_(s)


@router.post("/revalue")
async def revalue(request: Request, s=Depends(db_session)):
    n = await request.app.state.pipeline.revalue_active(s, limit=5000)
    return {"revalued": n}


@router.post("/telegram/test")
async def telegram_test(request: Request, s=Depends(db_session)):
    st = request.app.state
    l = (await s.execute(select(Listing).where(Listing.dup_of_id.is_(None), Listing.score.is_not(None))
                         .order_by(Listing.score.desc()).limit(1))).scalars().first()
    if not l:
        raise HTTPException(409, "Нет объявлений для тестового уведомления")
    chats = await st.notifier.chat_ids(s) or ([0] if isinstance(st.notifier.transport, LogTransport) else [])
    if not chats:
        raise HTTPException(409, "Нет подключённых чатов: отправьте боту /start <код> или задайте TELEGRAM_ALLOWED_CHAT_IDS")
    text = "🔔 <b>ТЕСТ</b>\n\n" + format_listing(l, st.settings.display_timezone)
    for c in chats:
        await st.notifier.transport.send(c, text, l.photos[0] if l.photos else None, listing_buttons(l))
    return {"mode": "telegram" if st.bot else "stub", "chats": len(chats), "preview": text}

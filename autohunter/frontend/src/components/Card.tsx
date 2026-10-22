import type { Listing } from "../types";
import { DRIVE, FUEL, SELLER, SOURCE, TRANS, ago, km, rub, scoreClass, timeOnly } from "../util";

export function Photo({ l }: { l: Listing }) {
  if (l.photos[0]) return <img className="photo" src={l.photos[0]} alt={l.title} loading="lazy" referrerPolicy="no-referrer" />;
  return <div className="photo ph"><b>{l.brand?.slice(0, 3).toUpperCase()}</b>нет фото</div>;
}

export function Deviation({ l }: { l: Listing }) {
  if (l.deviation_pct == null) return <span className="dev neutral">оценка недоступна</span>;
  const d = l.deviation_pct;
  const cls = d >= 10 ? "deal" : d < -5 ? "over" : "neutral";
  return <span className={`dev ${cls}`}>{d >= 0 ? `ниже рынка ${d.toFixed(0)}%` : `выше рынка ${(-d).toFixed(0)}%`}</span>;
}

export function ScoreBadge({ l }: { l: Listing }) {
  return <div className={`score ${scoreClass(l.score_label)}`} title={l.score_label_ru ?? ""}>{l.score ?? "—"}<small>из 100</small></div>;
}

export default function Card({ l, isNew, onOpen, onFav, onHide }: {
  l: Listing; isNew: boolean; onOpen: () => void; onFav: () => void; onHide: () => void;
}) {
  const specs = [
    l.year && `${l.year}`, l.engine_volume && `${l.engine_volume.toFixed(1)} ${l.fuel ? FUEL[l.fuel] ?? l.fuel : ""}`.trim(),
    l.transmission && (TRANS[l.transmission] ?? l.transmission), l.drive && (DRIVE[l.drive] ?? l.drive), l.mileage != null && km(l.mileage),
    l.generation,
  ].filter(Boolean) as string[];
  const lat = l.posted_at ? Math.max(0, Math.round((new Date(l.first_seen_at).getTime() - new Date(l.posted_at).getTime()) / 1000)) : null;
  return (
    <div className={"item" + (isNew ? " new" : "")}>
      <div onClick={onOpen} style={{ cursor: "pointer" }}><Photo l={l} /></div>
      <div>
        <h4 onClick={onOpen}>{l.title}</h4>
        <div className="specs">{specs.map((s, i) => <span key={i}>{s}</span>)}</div>
        <div style={{ margin: "6px 0" }}>
          <span className="price">{rub(l.price)}</span>{" "}
          {l.price < l.price_initial && <span className="badge">было {rub(l.price_initial)}</span>}
        </div>
        <div className="market">Рынок: {rub(l.market_price)} <Deviation l={l} />
          {l.confidence != null && l.market_price && <span className="muted small"> · достоверность {(l.confidence * 100).toFixed(0)}% · аналогов {l.comps_count}</span>}
        </div>
        <div>{l.warnings.slice(0, 3).map((w, i) => <span className="warn" key={i}>{w}</span>)}</div>
        <div className="meta">
          {isNew && <span className="badge fav">NEW</span>}
          <span className="badge">{SOURCE[l.source] ?? l.source}</span>
          {l.seller_type && <span className="badge">{SELLER[l.seller_type]}</span>}
          {l.repost_count > 0 && <span className="badge">перепубликаций: {l.repost_count}</span>}
          {[l.city, l.region !== l.city ? l.region : null].filter(Boolean).join(", ")} · обнаружено {timeOnly(l.first_seen_at)} ({ago(l.first_seen_at)})
          {lat != null && lat < 3600 && ` · через ${lat} с после публикации`}
        </div>
      </div>
      <div className="right">
        <ScoreBadge l={l} />
        <div className="actions">
          <a className="btn small" href={l.url} target="_blank" rel="noreferrer noopener">Открыть ↗</a>
          <button className={"btn small" + (l.favorite ? " on" : "")} onClick={onFav}>{l.favorite ? "★" : "☆"}</button>
          <button className="btn small" onClick={onHide} title="Скрыть">🙈</button>
        </div>
      </div>
    </div>
  );
}

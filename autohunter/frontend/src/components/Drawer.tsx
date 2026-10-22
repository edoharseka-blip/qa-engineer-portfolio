import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Detail } from "../types";
import { dateTime, km, rub } from "../util";
import { Deviation, ScoreBadge } from "./Card";

const PART_RU: Record<string, string> = { price: "Цена к рынку", liquidity: "Ликвидность", mileage: "Пробег", age: "Возраст", condition: "Состояние (по описанию)", price_history: "История цены", confidence: "Достоверность оценки", private_bonus: "Частный продавец" };

export default function Drawer({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const [d, setD] = useState<Detail | null>(null);
  useEffect(() => { setD(null); api<Detail>(`/api/listings/${id}`).then(setD).catch(() => onClose()); }, [id]); // eslint-disable-line
  useEffect(() => { const f = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f); }, [onClose]);
  const ex = d?.valuation?.explain;
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer">
        <div className="toolbar"><button className="btn small" onClick={onClose}>✕ Закрыть</button>{d && <a className="btn small primary" href={d.url} target="_blank" rel="noreferrer noopener">Открыть объявление ↗</a>}</div>
        {!d ? <div className="muted">Загрузка…</div> : (
          <div className="grid">
            <div className="toolbar">
              <div className="grow"><h2 style={{ margin: 0 }}>{d.title}</h2>
                <div className="muted">{[d.city, d.region].filter(Boolean).join(", ")} · {d.days_on_market} дн. в продаже · опубликовано {dateTime(d.posted_at)}</div></div>
              <ScoreBadge l={d} />
            </div>
            <div className="card">
              <div className="price">{rub(d.price)} <Deviation l={d} /></div>
              {d.market_price ? (
                <>
                  <div className="market">Оценка рынка (по ценам предложений): <b>{rub(d.market_price)}</b>; ожидаемая цена сделки ≈ {rub(ex?.expected_sale_price)}</div>
                  {d.market_low && d.market_high && (() => {
                    const lo = Math.min(d.market_low, d.price) * 0.95, hi = Math.max(d.market_high, d.price) * 1.05, p = (v: number) => ((v - lo) / (hi - lo)) * 100;
                    return <div className="range"><i style={{ left: p(d.market_low) + "%", width: p(d.market_high) - p(d.market_low) + "%" }} /><u style={{ left: p(d.price) + "%" }} title="Цена объявления" /></div>;
                  })()}
                  <div className="muted small">Жёлтая отметка — цена объявления; бирюзовая зона — межквартильный диапазон аналогов ({rub(d.market_low)} – {rub(d.market_high)}).</div>
                </>
              ) : <div className="muted">Недостаточно сопоставимых объявлений для оценки.</div>}
            </div>
            {d.warnings.length > 0 && <div>{d.warnings.map((w, i) => <span className="warn" key={i}>{w}</span>)}</div>}

            {ex && (
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Как посчитана оценка</h3>
                <div>Выборка: <b>{String(ex.tier)}</b>; аналогов: <b>{ex.comps_used}</b>; выбросов отброшено: {ex.outliers_removed}; дублей: {ex.duplicates_removed}.</div>
                <div>Достоверность: <b>{((d.confidence ?? 0) * 100).toFixed(0)}%</b> (аналоги {Math.round(ex.confidence_parts.n * 100)}%, разброс {Math.round(ex.confidence_parts.dispersion * 100)}%, критерии {Math.round(ex.confidence_parts.tier * 100)}%, полнота данных {Math.round(ex.confidence_parts.attributes * 100)}%).</div>
                <div className="muted small">Поправки: {(ex.year_slope * 100).toFixed(1)}%/год ({ex.year_slope_source}), {(ex.mileage_coef_per_10k_km * 100).toFixed(1)}% за каждые 10 тыс. км.</div>
                {(ex.notes as string[]).map((n, i) => <div key={i} className="warn">{n}</div>)}
                <div className="muted small" style={{ marginTop: 6 }}>{ex.disclaimer}</div>
              </div>
            )}

            {d.score_parts && (
              <div className="card">
                <h3 style={{ marginTop: 0 }}>Из чего сложился рейтинг {d.score}/100 — {d.score_label_ru}</h3>
                {Object.entries(d.score_parts).map(([k, v]) => k === "private_bonus" ? (
                  <div className="kv" key={k}><span>{PART_RU[k]}</span><span className="muted small">{v.note}</span><span>+{v.value}</span></div>
                ) : (
                  <div key={k}><div className="kv"><span>{PART_RU[k] ?? k}</span><div className="bar"><i style={{ width: v.value * 100 + "%" }} /></div><span>{Math.round(v.value * 100)}</span></div>
                    {v.note && <div className="muted small" style={{ marginLeft: 138, marginTop: -4 }}>{v.note}</div>}</div>
                ))}
              </div>
            )}

            <div className="card">
              <h3 style={{ marginTop: 0 }}>История цены</h3>
              {d.price_history.length > 1 ? (
                <ResponsiveContainer width="100%" height={160}><LineChart data={d.price_history.map((h) => ({ t: dateTime(h.at), price: h.price }))}>
                  <CartesianGrid stroke="#263040" /><XAxis dataKey="t" stroke="#8b98a9" fontSize={11} /><YAxis stroke="#8b98a9" fontSize={11} domain={["auto", "auto"]} tickFormatter={(v) => `${Math.round(v / 1000)}к`} />
                  <Tooltip contentStyle={{ background: "#161b22", border: "1px solid #263040" }} formatter={(v: number) => rub(v)} /><Line dataKey="price" stroke="#14b8a6" dot /></LineChart></ResponsiveContainer>
              ) : <div className="muted">Цена не менялась с момента обнаружения ({rub(d.price_initial)}).</div>}
              {d.repost_count > 0 && <div className="muted small">Обнаружено повторных публикаций/дублей: {d.repost_count}</div>}
            </div>

            <div className="card">
              <h3 style={{ marginTop: 0 }}>Характеристики</h3>
              <table><tbody>
                {([["Год", d.year], ["Поколение", d.generation], ["Двигатель", d.engine_volume ? `${d.engine_volume} л, ${d.power_hp ?? "?"} л.с.` : null], ["Пробег", d.mileage != null ? km(d.mileage) : null], ["Кузов", d.body], ["VIN", d.vin], ["Ликвидность модели", d.liquidity != null ? `${Math.round(d.liquidity * 100)}%` : "недостаточно данных"]] as [string, unknown][])
                  .filter(([, v]) => v).map(([k, v]) => <tr key={k}><th>{k}</th><td>{String(v)}</td></tr>)}
              </tbody></table>
              <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{d.description}</p>
            </div>

            {d.comparables.length > 0 && (
              <div className="card"><h3 style={{ marginTop: 0 }}>Аналоги (из расчёта)</h3>
                <table><thead><tr><th>Авто</th><th>Пробег</th><th>Цена</th></tr></thead><tbody>
                  {d.comparables.map((c) => <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => onOpen(c.id)}><td>{c.title}</td><td>{km(c.mileage)}</td><td>{rub(c.price)}</td></tr>)}
                </tbody></table></div>
            )}
            {d.duplicates.length > 0 && <div className="card"><h3 style={{ marginTop: 0 }}>Тот же автомобиль в других объявлениях</h3>
              {d.duplicates.map((x) => <div key={x.id}><a href={x.url} target="_blank" rel="noreferrer noopener">{x.source}</a> — {rub(x.price)}</div>)}</div>}
          </div>
        )}
      </aside>
    </>
  );
}

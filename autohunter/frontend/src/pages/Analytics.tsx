import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import type { Filter, Meta } from "../types";
import { rub } from "../util";

interface Group { name: string; count: number; median_price: number | null; median_mileage: number | null; median_year: number | null }
interface Data {
  count: number; median_price: number | null; p25: number | null; p75: number | null; median_age_days: number | null; note: string;
  histogram?: { from: number; to: number; count: number }[]; age_distribution: { bucket: string; count: number }[];
  by_generation: Group[]; by_engine: Group[]; by_region: Group[]; trend: { day: string; median_price: number; count: number }[];
  liquidity: { name: string; count: number; liquidity: number | null; median_age_days: number }[];
}
const tip = { contentStyle: { background: "#161b22", border: "1px solid #263040" }, labelStyle: { color: "#e6edf3" } };
const ax = { stroke: "#8b98a9", fontSize: 11 };

export default function Analytics({ meta }: { meta: Meta }) {
  const [f, setF] = useState<Filter>({});
  const [d, setD] = useState<Data | null>(null);
  const models = (f.brands?.length ? f.brands : meta.brands).flatMap((b) => meta.models[b] ?? []);
  useEffect(() => { api<Data>("/api/analytics", { body: f }).then(setD).catch(() => {}); }, [f]);
  return (
    <div className="grid">
      <div className="toolbar">
        <h2 style={{ margin: 0 }}>Аналитика рынка</h2><div className="grow" />
        <select style={{ width: "auto" }} value={f.brands?.[0] ?? ""} onChange={(e) => setF(e.target.value ? { brands: [e.target.value] } : {})}>
          <option value="">Все марки</option>{meta.brands.map((b) => <option key={b}>{b}</option>)}</select>
        <select style={{ width: "auto" }} value={f.models?.[0] ?? ""} onChange={(e) => setF({ ...f, models: e.target.value ? [e.target.value] : [] })}>
          <option value="">Все модели</option>{models.map((m) => <option key={m}>{m}</option>)}</select>
        <select style={{ width: "auto" }} value={f.regions?.[0] ?? ""} onChange={(e) => setF({ ...f, regions: e.target.value ? [e.target.value] : [] })}>
          <option value="">Все регионы</option>{meta.regions.map((r) => <option key={r}>{r}</option>)}</select>
      </div>
      {!d ? <div className="muted">Загрузка…</div> : (
        <>
          <div className="grid g4">
            <div className="stat"><div className="v">{d.count}</div><div className="l">предложений</div></div>
            <div className="stat"><div className="v">{rub(d.median_price)}</div><div className="l">медианная цена</div></div>
            <div className="stat"><div className="v">{rub(d.p25)} – {rub(d.p75)}</div><div className="l">межквартильный диапазон</div></div>
            <div className="stat"><div className="v">{d.median_age_days ?? "—"} дн.</div><div className="l">медианный возраст объявлений</div></div>
          </div>
          <div className="grid g2">
            <div className="card"><h3 style={{ marginTop: 0 }}>Распределение цен</h3>
              <ResponsiveContainer width="100%" height={220}><BarChart data={d.histogram?.map((b) => ({ label: `${Math.round(b.from / 1000)}к`, count: b.count }))}>
                <CartesianGrid stroke="#263040" /><XAxis dataKey="label" {...ax} /><YAxis {...ax} allowDecimals={false} /><Tooltip {...tip} /><Bar dataKey="count" name="Объявлений" fill="#14b8a6" /></BarChart></ResponsiveContainer></div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Возраст объявлений</h3>
              <ResponsiveContainer width="100%" height={220}><BarChart data={d.age_distribution}>
                <CartesianGrid stroke="#263040" /><XAxis dataKey="bucket" {...ax} /><YAxis {...ax} allowDecimals={false} /><Tooltip {...tip} /><Bar dataKey="count" name="Объявлений" fill="#38bdf8" /></BarChart></ResponsiveContainer></div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Динамика медианной цены (по дате публикации)</h3>
              <ResponsiveContainer width="100%" height={220}><LineChart data={d.trend}>
                <CartesianGrid stroke="#263040" /><XAxis dataKey="day" {...ax} /><YAxis {...ax} domain={["auto", "auto"]} tickFormatter={(v) => `${Math.round(v / 1000)}к`} /><Tooltip {...tip} formatter={(v: number) => rub(v)} />
                <Line dataKey="median_price" name="Медиана" stroke="#f59e0b" dot={false} /></LineChart></ResponsiveContainer>
              <div className="muted small">Это динамика состава выставленных объявлений, а не индекс цен одной и той же машины.</div></div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Поколения: медианная цена</h3>
              <ResponsiveContainer width="100%" height={Math.max(180, d.by_generation.slice(0, 10).length * 30)}><BarChart layout="vertical" data={d.by_generation.slice(0, 10)}>
                <CartesianGrid stroke="#263040" /><XAxis type="number" {...ax} tickFormatter={(v) => `${Math.round(v / 1000)}к`} /><YAxis type="category" dataKey="name" width={150} {...ax} />
                <Tooltip {...tip} formatter={(v: number) => rub(v)} /><Bar dataKey="median_price" name="Медиана" fill="#a78bfa" /></BarChart></ResponsiveContainer></div>
          </div>
          <div className="grid g2">
            <div className="card"><h3 style={{ marginTop: 0 }}>Двигатели</h3>
              <table><thead><tr><th>Двигатель</th><th>Шт.</th><th>Медиана</th><th>Пробег</th></tr></thead><tbody>
                {d.by_engine.map((g) => <tr key={g.name}><td>{g.name}</td><td>{g.count}</td><td>{rub(g.median_price)}</td><td>{g.median_mileage?.toLocaleString("ru-RU") ?? "—"}</td></tr>)}</tbody></table></div>
            <div className="card"><h3 style={{ marginTop: 0 }}>Регионы</h3>
              <table><thead><tr><th>Регион</th><th>Шт.</th><th>Медиана</th></tr></thead><tbody>
                {d.by_region.map((g) => <tr key={g.name}><td>{g.name}</td><td>{g.count}</td><td>{rub(g.median_price)}</td></tr>)}</tbody></table></div>
          </div>
          <div className="card"><h3 style={{ marginTop: 0 }}>Ликвидность моделей</h3>
            <table><thead><tr><th>Модель</th><th>Предложений</th><th>Ликвидность</th><th>Медианный возраст объявления</th></tr></thead><tbody>
              {d.liquidity.map((g) => <tr key={g.name}><td>{g.name}</td><td>{g.count}</td>
                <td>{g.liquidity != null ? <div style={{ display: "flex", gap: 8, alignItems: "center" }}><div className="bar" style={{ width: 120 }}><i style={{ width: g.liquidity * 100 + "%" }} /></div>{Math.round(g.liquidity * 100)}%</div> : "нет данных"}</td>
                <td>{g.median_age_days} дн.</td></tr>)}</tbody></table>
            <div className="muted small">Ликвидность = экспертная популярность модели (априори), скорректированная возрастом активных объявлений, когда их ≥5. Это оценка, а не статистика продаж.</div></div>
          <div className="muted small">{d.note}</div>
        </>
      )}
    </div>
  );
}

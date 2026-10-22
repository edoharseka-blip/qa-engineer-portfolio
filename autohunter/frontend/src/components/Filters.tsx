import type { Filter, Meta } from "../types";
import { num } from "../util";

const toggle = (arr: string[] | undefined, v: string) => { const a = arr ?? []; return a.includes(v) ? a.filter((x) => x !== v) : [...a, v]; };

function Chips({ options, value, onChange, labels }: { options: string[]; value?: string[]; onChange: (v: string[]) => void; labels?: Record<string, string> }) {
  return <div className="chips">{options.map((o) => <span key={o} className={"chip" + (value?.includes(o) ? " on" : "")} onClick={() => onChange(toggle(value, o))}>{labels?.[o] ?? o}</span>)}</div>;
}

export default function Filters({ f, setF, meta, className }: { f: Filter; setF: (f: Filter) => void; meta: Meta; className?: string }) {
  const set = (p: Partial<Filter>) => setF({ ...f, ...p });
  const models = (f.brands?.length ? f.brands : meta.brands).flatMap((b) => meta.models[b] ?? []);
  const hours = (h: number) => new Date(Date.now() - h * 3600_000).toISOString();
  return (
    <div className={"card filters " + (className ?? "")}>
      <label className="f">Поиск по тексту<input value={f.q ?? ""} placeholder="напр. xDrive, один хозяин" onChange={(e) => set({ q: e.target.value || undefined })} /></label>
      <div className="f muted small">Марка<Chips options={meta.brands} value={f.brands} onChange={(v) => set({ brands: v, models: [] })} /></div>
      <div className="f muted small">Модель<Chips options={models} value={f.models} onChange={(v) => set({ models: v })} /></div>
      {f.models?.length === 1 && (meta.generations[f.models[0]]?.length ?? 0) > 0 && <div className="f muted small">Поколение<Chips options={meta.generations[f.models[0]]} value={f.generations} onChange={(v) => set({ generations: v })} /></div>}
      <div className="row2"><label className="f">Год от<input inputMode="numeric" value={f.year_min ?? ""} onChange={(e) => set({ year_min: num(e.target.value) })} /></label><label className="f">до<input inputMode="numeric" value={f.year_max ?? ""} onChange={(e) => set({ year_max: num(e.target.value) })} /></label></div>
      <div className="row2"><label className="f">Цена от, ₽<input inputMode="numeric" value={f.price_min ?? ""} onChange={(e) => set({ price_min: num(e.target.value) })} /></label><label className="f">до<input inputMode="numeric" value={f.price_max ?? ""} onChange={(e) => set({ price_max: num(e.target.value) })} /></label></div>
      <label className="f">Пробег до, км<input inputMode="numeric" value={f.mileage_max ?? ""} onChange={(e) => set({ mileage_max: num(e.target.value) })} /></label>
      <div className="row2"><label className="f">Объём от, л<input inputMode="decimal" value={f.engine_volume_min ?? ""} onChange={(e) => set({ engine_volume_min: num(e.target.value) })} /></label><label className="f">до<input inputMode="decimal" value={f.engine_volume_max ?? ""} onChange={(e) => set({ engine_volume_max: num(e.target.value) })} /></label></div>
      <div className="f muted small">Двигатель<Chips options={["petrol", "diesel"]} labels={{ petrol: "бензин", diesel: "дизель" }} value={f.fuels} onChange={(v) => set({ fuels: v })} /></div>
      <div className="f muted small">КПП<Chips options={["AT", "MT", "AMT", "CVT"]} labels={{ AT: "автомат", MT: "механика", AMT: "робот", CVT: "вариатор" }} value={f.transmissions} onChange={(v) => set({ transmissions: v })} /></div>
      <div className="f muted small">Привод<Chips options={["AWD", "RWD", "FWD"]} labels={{ AWD: "полный", RWD: "задний", FWD: "передний" }} value={f.drives} onChange={(v) => set({ drives: v })} /></div>
      <div className="f muted small">Регион<Chips options={meta.regions} value={f.regions} onChange={(v) => set({ regions: v })} /></div>
      <div className="f muted small">Продавец<Chips options={["private", "dealer"]} labels={{ private: "частный", dealer: "дилер" }} value={f.seller_types} onChange={(v) => set({ seller_types: v })} /></div>
      <div className="f muted small">Источник<Chips options={meta.sources} value={f.sources} onChange={(v) => set({ sources: v })} /></div>
      <label className="f">Ниже рынка не менее, %<input inputMode="decimal" value={f.deviation_min ?? ""} onChange={(e) => set({ deviation_min: num(e.target.value) })} /></label>
      <label className="f">Рейтинг не ниже<input inputMode="numeric" value={f.score_min ?? ""} onChange={(e) => set({ score_min: num(e.target.value) })} /></label>
      <div className="f muted small">Опубликовано<div className="chips">
        {[["1 ч", 1], ["6 ч", 6], ["24 ч", 24], ["7 дн", 168]].map(([l, h]) => <span key={l} className="chip" onClick={() => set({ posted_after: hours(h as number) })}>{l}</span>)}
        <span className="chip" onClick={() => set({ posted_after: undefined })}>любое</span></div></div>
      <div className="chips"><span className={"chip" + (f.deviation_min === 10 ? " on" : "")} onClick={() => set({ deviation_min: f.deviation_min === 10 ? undefined : 10 })}>🔥 дешевле рынка ≥10%</span>
        <span className={"chip" + (f.only_favorites ? " on" : "")} onClick={() => set({ only_favorites: !f.only_favorites || undefined })}>★ избранное</span></div>
      <button className="btn" onClick={() => setF({})}>Сбросить фильтры</button>
    </div>
  );
}

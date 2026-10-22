import { useEffect, useState } from "react";
import { api } from "../api";
import type { Filter, Profile } from "../types";

interface Cfg {
  scoring: { weights: Record<string, number>; thresholds: Record<string, number>; private_bonus: number; risk_cap: number; suspicious_deviation: number; km_per_year: number };
  valuation: Record<string, number>; notifications_paused: boolean;
}
const W_RU: Record<string, string> = { price: "Цена к рынку", liquidity: "Ликвидность", mileage: "Пробег", age: "Возраст", condition: "Состояние", price_history: "История цены", confidence: "Достоверность" };
const V_RU: Record<string, string> = { min_comps: "Мин. аналогов для уверенной оценки", min_fallback: "Мин. аналогов (приблизительно)", year_coef: "Потеря цены за год (доля)", mileage_coef_10k: "Потеря цены за 10 тыс. км (доля)", adj_cap: "Макс. поправка", outlier_z: "Порог выбросов (mod. z)", asking_discount: "Скидка цены предложения → сделки (доля)" };

export default function SettingsPage({ profiles, reloadProfiles, onApply }: { profiles: Profile[]; reloadProfiles: () => void; onApply: (f: Filter) => void }) {
  const [c, setC] = useState<Cfg | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => api<Cfg>("/api/settings").then(setC);
  useEffect(() => { load(); }, []);
  if (!c) return <div className="muted">Загрузка…</div>;
  const save = async () => {
    try { const r = await api<Cfg>("/api/settings", { method: "PUT", body: { scoring: c.scoring, valuation: c.valuation } }); setC(r); setMsg("Сохранено. Нажмите «Пересчитать», чтобы применить к существующим объявлениям."); }
    catch (e) { setMsg("Ошибка: " + (e as Error).message); }
  };
  const revalue = async () => { const r = await api<{ revalued: number }>("/api/revalue", { method: "POST", body: {} }); setMsg(`Пересчитано объявлений: ${r.revalued}`); };
  const setW = (k: string, v: number) => setC({ ...c, scoring: { ...c.scoring, weights: { ...c.scoring.weights, [k]: v } } });
  const setT = (k: string, v: number) => setC({ ...c, scoring: { ...c.scoring, thresholds: { ...c.scoring.thresholds, [k]: v } } });
  const nm = (v: string) => Number(v.replace(",", "."));
  const upd = async (p: Profile, patch: Partial<Profile>) => { await api(`/api/profiles/${p.id}`, { method: "PUT", body: { ...p, ...patch } }); reloadProfiles(); };
  return (
    <div className="grid">
      <h2 style={{ margin: 0 }}>Настройки</h2>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Профили поиска и уведомлений</h3>
        <div className="muted small">Профиль с включёнными уведомлениями определяет, что приходит в Telegram: объявление подходит под фильтры И (рейтинг ≥ порога ИЛИ отклонение ≥ порога). Фильтры меняются через вкладку «Лента» → «💾», либо командой /set в боте.</div>
        <table><thead><tr><th>Название</th><th>Активен</th><th>Telegram</th><th>Рейтинг ≥</th><th>Ниже рынка ≥, %</th><th /></tr></thead><tbody>
          {profiles.map((p) => <tr key={p.id}><td>{p.name}</td>
            <td><input type="checkbox" checked={p.active} onChange={(e) => upd(p, { active: e.target.checked })} style={{ width: "auto" }} /></td>
            <td><input type="checkbox" checked={p.notify} onChange={(e) => upd(p, { notify: e.target.checked })} style={{ width: "auto" }} /></td>
            <td><input style={{ width: 70 }} defaultValue={p.notify_min_score} onBlur={(e) => upd(p, { notify_min_score: nm(e.target.value) })} /></td>
            <td><input style={{ width: 70 }} defaultValue={p.notify_min_deviation} onBlur={(e) => upd(p, { notify_min_deviation: nm(e.target.value) })} /></td>
            <td><div className="actions"><button className="btn small" onClick={() => onApply(p.filters)}>Открыть в ленте</button>
              <button className="btn small" onClick={async () => { if (confirm(`Удалить «${p.name}»?`)) { await api(`/api/profiles/${p.id}`, { method: "DELETE" }); reloadProfiles(); } }}>🗑</button></div></td></tr>)}
        </tbody></table>
      </div>
      <div className="grid g2">
        <div className="card"><h3 style={{ marginTop: 0 }}>Веса рейтинга</h3>
          {Object.entries(c.scoring.weights).map(([k, v]) => <label className="f" key={k} style={{ marginBottom: 8 }}>{W_RU[k] ?? k}: {v}
            <input type="range" min={0} max={60} value={v} onChange={(e) => setW(k, Number(e.target.value))} /></label>)}
          <div className="muted small">Веса нормируются: итог всегда в диапазоне 0–100.</div></div>
        <div className="card"><h3 style={{ marginTop: 0 }}>Пороги и ограничения</h3>
          <div className="row2">{(["great", "good", "normal"] as const).map((k) => <label className="f" key={k}>{{ great: "Очень интересно ≥", good: "Стоит изучить ≥", normal: "Обычное ≥" }[k]}
            <input value={c.scoring.thresholds[k]} onChange={(e) => setT(k, nm(e.target.value))} /></label>)}
            <label className="f">Бонус частнику, баллов<input value={c.scoring.private_bonus} onChange={(e) => setC({ ...c, scoring: { ...c.scoring, private_bonus: nm(e.target.value) } })} /></label>
            <label className="f">Потолок при рисках<input value={c.scoring.risk_cap} onChange={(e) => setC({ ...c, scoring: { ...c.scoring, risk_cap: nm(e.target.value) } })} /></label>
            <label className="f">«Подозрительно дёшево» от, %<input value={c.scoring.suspicious_deviation} onChange={(e) => setC({ ...c, scoring: { ...c.scoring, suspicious_deviation: nm(e.target.value) } })} /></label>
            <label className="f">Ожидаемый пробег, км/год<input value={c.scoring.km_per_year} onChange={(e) => setC({ ...c, scoring: { ...c.scoring, km_per_year: nm(e.target.value) } })} /></label></div>
          <h3>Параметры оценки рынка</h3>
          <div className="row2">{Object.entries(c.valuation).map(([k, v]) => <label className="f" key={k}>{V_RU[k] ?? k}<input value={v} onChange={(e) => setC({ ...c, valuation: { ...c.valuation, [k]: nm(e.target.value) } })} /></label>)}</div></div>
      </div>
      <div className="toolbar"><button className="btn primary" onClick={save}>Сохранить</button><button className="btn" onClick={revalue}>Пересчитать все объявления</button><span className="muted">{msg}</span></div>
    </div>
  );
}

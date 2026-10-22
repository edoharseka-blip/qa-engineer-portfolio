import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import Card from "../components/Card";
import Drawer from "../components/Drawer";
import Filters from "../components/Filters";
import type { Filter, Listing, Meta, Profile } from "../types";
import { useInterval } from "../util";

const PAGE = 30;

export default function Feed({ meta, profiles, reloadProfiles, applied, setApplied }: {
  meta: Meta; profiles: Profile[]; reloadProfiles: () => void;
  applied: { filter: Filter; key: number } | null; setApplied: (a: null) => void;
}) {
  const [f, setF] = useState<Filter>({});
  const [sort, setSort] = useState("new");
  const [items, setItems] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [live, setLive] = useState(true);
  const [open, setOpen] = useState<number | null>(null);
  const [showF, setShowF] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(false);
  const baseline = useRef<number>(0);     // максимальный id, виденный при последнем «просмотре»
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const reqSeq = useRef(0);

  useEffect(() => { if (applied) { setF(applied.filter); setApplied(null); } }, [applied, setApplied]);

  const load = useCallback(async (reset: boolean, offset = 0) => {
    const seq = ++reqSeq.current;
    setLoading(true);
    try {
      const r = await api<{ total: number; max_id: number; items: Listing[] }>("/api/listings/search", { body: { filter: f, sort, limit: PAGE, offset } });
      if (seq !== reqSeq.current) return;
      setTotal(r.total);
      setItems((prev) => (reset ? r.items : [...prev, ...r.items]));
      if (reset) {
        if (baseline.current === 0) baseline.current = r.max_id;
        setNewIds((prev) => { const s = new Set(prev); r.items.forEach((i) => i.id > baseline.current && s.add(i.id)); return s; });
      }
    } finally { if (seq === reqSeq.current) setLoading(false); }
  }, [f, sort]);

  useEffect(() => { baseline.current = 0; setNewIds(new Set()); load(true); }, [load]);

  // «живое» обновление без перезагрузки страницы: подтягиваем первую страницу, не сбрасывая прокрутку
  const refresh = useCallback(async () => {
    if (document.hidden || open !== null) return;
    const seq = reqSeq.current;
    const r = await api<{ total: number; max_id: number; items: Listing[] }>("/api/listings/search", { body: { filter: f, sort, limit: PAGE, offset: 0 } }).catch(() => null);
    if (!r || seq !== reqSeq.current) return;
    setTotal(r.total);
    setItems((prev) => {
      const fresh = new Map(r.items.map((i) => [i.id, i]));
      const merged = prev.map((p) => fresh.get(p.id) ?? p);
      const known = new Set(prev.map((p) => p.id));
      const added = r.items.filter((i) => !known.has(i.id));
      if (added.length && sort === "new") { setToast(`Новых объявлений: ${added.length}`); setNewIds((s) => new Set([...s, ...added.map((a) => a.id)])); return [...added, ...merged]; }
      return merged;
    });
  }, [f, sort, open]);
  useInterval(refresh, live ? 5000 : null);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(""), 3500); return () => clearTimeout(t); }, [toast]);

  const act = async (id: number, what: "favorite" | "hide") => {
    await api(`/api/listings/${id}/${what}`, { method: "POST" });
    if (what === "hide") { setItems((p) => p.filter((i) => i.id !== id)); setTotal((t) => t - 1); }
    else setItems((p) => p.map((i) => (i.id === id ? { ...i, favorite: !i.favorite } : i)));
  };
  const saveProfile = async () => {
    if (!saveName.trim()) return;
    try { await api("/api/profiles", { body: { name: saveName.trim(), filters: f, notify: false } }); setSaveName(""); reloadProfiles(); setToast("Профиль сохранён"); }
    catch (e) { setToast((e as Error).message); }
  };

  return (
    <div className="layout">
      <Filters f={f} setF={setF} meta={meta} className={showF ? "" : "closed"} />
      <div>
        <div className="toolbar">
          <button className="btn mobile-only" onClick={() => setShowF((v) => !v)}>⚙ Фильтры</button>
          <b>{total.toLocaleString("ru-RU")} объявлений</b>
          <select style={{ width: "auto" }} value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="new">Сначала новые</option><option value="score">По рейтингу</option><option value="deviation">Дешевле рынка</option>
            <option value="price_asc">Цена ↑</option><option value="price_desc">Цена ↓</option><option value="posted">По дате публикации</option>
          </select>
          <button className={"btn" + (live ? " on" : "")} onClick={() => setLive((v) => !v)}>{live ? "● Обновляется" : "○ Пауза"}</button>
          <div className="grow" />
          <select style={{ width: "auto" }} value="" onChange={(e) => { const p = profiles.find((x) => x.id === Number(e.target.value)); if (p) setF(p.filters); }}>
            <option value="">Профиль…</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input style={{ width: 150 }} placeholder="Сохранить как…" value={saveName} onChange={(e) => setSaveName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && saveProfile()} />
          <button className="btn" onClick={saveProfile}>💾</button>
        </div>
        <div className="list">
          {items.map((l) => <Card key={l.id} l={l} isNew={newIds.has(l.id)} onOpen={() => setOpen(l.id)} onFav={() => act(l.id, "favorite")} onHide={() => act(l.id, "hide")} />)}
          {!items.length && !loading && <div className="card muted">Ничего не найдено. Измените фильтры.</div>}
          {items.length < total && <button className="btn" disabled={loading} onClick={() => load(false, items.length)}>{loading ? "Загрузка…" : "Показать ещё"}</button>}
        </div>
      </div>
      {open !== null && <Drawer id={open} onClose={() => setOpen(null)} onOpen={setOpen} />}
      {toast && <div className="toast" onClick={() => { setToast(""); window.scrollTo({ top: 0, behavior: "smooth" }); }}>{toast}</div>}
    </div>
  );
}

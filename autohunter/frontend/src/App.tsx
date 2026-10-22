import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import Feed from "./pages/Feed";
import Analytics from "./pages/Analytics";
import Monitoring from "./pages/Monitoring";
import SettingsPage from "./pages/Settings";
import type { Filter, Meta, Profile } from "./types";

const TABS = [["feed", "Лента"], ["analytics", "Аналитика"], ["monitoring", "Мониторинг"], ["settings", "Настройки"]] as const;
type Tab = (typeof TABS)[number][0];

function Login({ onDone }: { onDone: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const go = async (e: React.FormEvent) => {
    e.preventDefault();
    try { const r = await api<{ token: string }>("/api/auth/login", { body: { password: pw } }); setToken(r.token); onDone(); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <form className="card login" onSubmit={go}>
      <div className="logo">Auto<b>Hunter</b></div>
      <input type="password" placeholder="Пароль" value={pw} onChange={(e) => setPw(e.target.value)} autoFocus />
      {err && <div className="err">{err}</div>}
      <button className="btn primary">Войти</button>
    </form>
  );
}

export default function App() {
  const [authed, setAuthed] = useState(!!getToken());
  const [tab, setTab] = useState<Tab>("feed");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [applied, setApplied] = useState<{ filter: Filter; key: number } | null>(null);

  useEffect(() => { const f = () => setAuthed(false); window.addEventListener("autohunter:logout", f); return () => window.removeEventListener("autohunter:logout", f); }, []);
  const reloadProfiles = () => api<Profile[]>("/api/profiles").then(setProfiles).catch(() => {});
  useEffect(() => {
    if (!authed) return;
    api<Meta>("/api/meta").then(setMeta).catch(() => {});
    reloadProfiles();
  }, [authed]);

  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  return (
    <>
      <div className="topbar">
        <div className="logo">Auto<b>Hunter</b></div>
        <div className="tabs">{TABS.map(([k, l]) => <button key={k} className={"tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>)}</div>
        <button className="btn small" onClick={() => { setToken(""); setAuthed(false); }}>Выйти</button>
      </div>
      {meta?.demo_mode && <div className="banner">⚠️ Демонстрационный режим: показаны синтетические объявления, не реальные. Подключите источники в .env (см. README).</div>}
      <div className="page">
        {tab === "feed" && meta && <Feed meta={meta} profiles={profiles} reloadProfiles={reloadProfiles} applied={applied} setApplied={setApplied} />}
        {tab === "analytics" && meta && <Analytics meta={meta} />}
        {tab === "monitoring" && <Monitoring />}
        {tab === "settings" && <SettingsPage profiles={profiles} reloadProfiles={reloadProfiles} onApply={(f) => { setApplied({ filter: f, key: Date.now() }); setTab("feed"); }} />}
      </div>
    </>
  );
}

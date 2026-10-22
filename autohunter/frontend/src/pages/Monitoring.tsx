import { useState } from "react";
import { api } from "../api";
import { SOURCE, dateTime, useInterval } from "../util";
import { useEffect } from "react";

interface Lat { avg: number | null; p95: number | null; samples: number; synthetic?: boolean }
interface Src {
  name: string; title: string; configured: boolean; is_demo: boolean; note: string; listings: number; last_success_at: string | null;
  last_error: string | null; last_error_at: string | null; consecutive_failures: number; processed_total: number; new_total: number;
  error_total: number; detection_latency_s: Lat;
}
interface Mon {
  sources: Src[]; total_listings: number; notification_latency_s: Lat; latency_note: string; server_time: string;
  telegram: { mode: string; running: boolean; last_error: string | null; sent_total: number; chats: number; paused: boolean };
}
const sec = (v: number | null) => (v == null ? "—" : `${v} с`);

export default function Monitoring() {
  const [m, setM] = useState<Mon | null>(null);
  const [preview, setPreview] = useState("");
  const [err, setErr] = useState("");
  const load = () => api<Mon>("/api/monitoring").then(setM).catch(() => {});
  useEffect(() => { load(); }, []);
  useInterval(load, 5000);
  const test = async () => {
    setErr(""); setPreview("");
    try { const r = await api<{ mode: string; chats: number; preview: string }>("/api/telegram/test", { method: "POST", body: {} }); setPreview(`Режим: ${r.mode}, чатов: ${r.chats}\n\n${r.preview.replace(/<[^>]+>/g, "")}`); load(); }
    catch (e) { setErr((e as Error).message); }
  };
  if (!m) return <div className="muted">Загрузка…</div>;
  const t = m.telegram;
  return (
    <div className="grid">
      <h2 style={{ margin: 0 }}>Мониторинг системы</h2>
      <div className="grid g4">
        <div className="stat"><div className="v">{m.total_listings}</div><div className="l">объявлений в базе</div></div>
        <div className="stat"><div className="v">{sec(m.notification_latency_s.avg)} / {sec(m.notification_latency_s.p95)}</div><div className="l">обнаружение → уведомление (средн. / p95), n={m.notification_latency_s.samples}</div></div>
        <div className="stat"><div className="v">{t.sent_total}</div><div className="l">уведомлений отправлено</div></div>
      </div>
      <div className="grid g2">
        {m.sources.map((s) => (
          <div className="card" key={s.name}>
            <h3 style={{ marginTop: 0, color: "inherit", textTransform: "none", fontSize: 16 }}>
              <span className={"dot " + (!s.configured ? "off" : s.consecutive_failures ? "bad" : s.last_success_at ? "ok" : "off")} />{SOURCE[s.name] ?? s.title}
              {s.is_demo && <span className="badge demo" style={{ marginLeft: 8 }}>демо</span>}</h3>
            <div className="muted small">{s.note}</div>
            {!s.configured && <div className="warn">Не настроен (нужен ключ/доступ) — см. README</div>}
            <table><tbody>
              <tr><th>Последнее успешное обновление</th><td>{dateTime(s.last_success_at)}</td></tr>
              <tr><th>Объявлений / обработано / новых</th><td>{s.listings} / {s.processed_total} / {s.new_total}</td></tr>
              <tr><th>Задержка обнаружения, средн. / p95</th><td>{sec(s.detection_latency_s.avg)} / {sec(s.detection_latency_s.p95)} <span className="muted small">(n={s.detection_latency_s.samples}{s.detection_latency_s.synthetic ? ", синтетическая" : ""})</span></td></tr>
              <tr><th>Ошибок всего / подряд</th><td>{s.error_total} / {s.consecutive_failures}</td></tr>
            </tbody></table>
            {s.last_error && <div className="err">Последняя ошибка ({dateTime(s.last_error_at)}): {s.last_error}</div>}
          </div>
        ))}
        <div className="card">
          <h3 style={{ marginTop: 0, color: "inherit", textTransform: "none", fontSize: 16 }}><span className={"dot " + (t.mode === "telegram" ? (t.running ? "ok" : "bad") : "off")} />Telegram-бот</h3>
          <table><tbody>
            <tr><th>Режим</th><td>{t.mode === "telegram" ? "боевой (токен задан)" : "заглушка — токен не задан, сообщения в логе"}</td></tr>
            <tr><th>Состояние</th><td>{t.mode === "telegram" ? (t.running ? "работает" : "остановлен") : "—"}</td></tr>
            <tr><th>Чатов</th><td>{t.chats}</td></tr><tr><th>Уведомления</th><td>{t.paused ? "⏸ на паузе" : "▶ включены"}</td></tr>
          </tbody></table>
          {t.last_error && <div className="err">{t.last_error}</div>}
          <button className="btn primary" style={{ marginTop: 10 }} onClick={test}>Отправить тестовое уведомление</button>
          {err && <div className="err">{err}</div>}
          {preview && <pre className="preview">{preview}</pre>}
        </div>
      </div>
      <div className="muted small">{m.latency_note} Целевая задержка 15–30 с не заявляется как достигнутая, пока не измерена на реальных источниках.</div>
    </div>
  );
}

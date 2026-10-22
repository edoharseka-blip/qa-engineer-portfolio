const KEY = "autohunter.token";
export const getToken = () => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } };
export const setToken = (t: string) => { try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch { /* ignore */ } };

export class ApiError extends Error { constructor(public status: number, msg: string) { super(msg); } }

export async function api<T>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(path, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401 && path !== "/api/auth/login") { setToken(""); window.dispatchEvent(new Event("autohunter:logout")); }
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new ApiError(r.status, msg);
  }
  return r.json();
}

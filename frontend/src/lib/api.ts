// JSON client for the Complanning API. Sends the CSRF header on every request.

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  extra: Record<string, unknown>;
  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}, extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.extra = extra;
  }
}

type Listener = (err: ApiError) => void;
const authListeners = new Set<Listener>();
export function onAuthError(fn: Listener) {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

/** The last few errors the user met in this tab, so the Assistant can explain them. Kept in memory only. */
export interface SeenError { at: string; page: string; action: string; code: string; message: string; fields: Record<string, string> }
const seen: SeenError[] = [];
const QUIET = /^\/api\/(assistant|auth)\//;
function remember(method: string, path: string, err: ApiError) {
  if (QUIET.test(path) || err.status === 401 || err.code === "network") return;
  const action = `${method} ${path.split("?")[0].replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, ":id")}`;
  const fields: Record<string, string> = {};
  Object.entries(err.fields ?? {}).slice(0, 8).forEach(([k, v]) => { fields[k.slice(0, 60)] = String(v).slice(0, 300); });
  seen.unshift({ at: new Date().toISOString(), page: typeof location !== "undefined" ? location.pathname : "", action,
    code: err.code, message: String(err.message).slice(0, 400), fields });
  seen.length = Math.min(seen.length, 5);
}
export function recentErrors(maxAgeMinutes = 30): SeenError[] {
  const since = Date.now() - maxAgeMinutes * 60_000;
  return seen.filter((e) => Date.parse(e.at) >= since);
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "complanning" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "network");
  }
  const text = await res.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!res.ok) {
    const e = data?.error ?? {};
    const { code, message, fields, ...extra } = e;
    const err = new ApiError(res.status, code ?? "server_error", message ?? res.statusText, fields ?? {}, extra);
    if (res.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/me") {
      authListeners.forEach((fn) => fn(err));
    }
    remember(method, path, err);
    throw err;
  }
  return data as T;
}

export const get = <T = any>(path: string) => api<T>("GET", path);
export const post = <T = any>(path: string, body: unknown = {}) => api<T>("POST", path, body);
export const patch = <T = any>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const put = <T = any>(path: string, body: unknown) => api<T>("PUT", path, body);
export const del = <T = any>(path: string) => api<T>("DELETE", path);

export function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

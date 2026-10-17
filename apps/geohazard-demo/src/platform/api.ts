import { reactive } from "vue";
const BASE_KEY = "geohazard-api-base";
const TOKEN_KEY = "geohazard-api-token";
export const connectionSettings = reactive({ base: sessionStorage.getItem(BASE_KEY) || "/api/v1", token: sessionStorage.getItem(TOKEN_KEY) || "", revision: 0 });
export function saveConnection(base: string, token: string) {
  const cleaned = base.trim().replace(/\/+$/, "") || "/api/v1";
  const parsed = new URL(cleaned, window.location.origin);
  if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("后端地址必须为 HTTP 或 HTTPS 地址");
  if (parsed.username || parsed.password || parsed.search || parsed.hash) throw new Error("后端地址不能包含认证信息、查询参数或片段");
  sessionStorage.setItem(BASE_KEY, cleaned);
  if (token.trim()) sessionStorage.setItem(TOKEN_KEY, token.trim());
  else sessionStorage.removeItem(TOKEN_KEY);
  connectionSettings.base = cleaned;
  connectionSettings.token = token.trim();
  connectionSettings.revision++;
}
function headers(json = false) {
  const result = new Headers();
  if (json) result.set("Content-Type", "application/json");
  if (connectionSettings.token) result.set("Authorization", `Bearer ${connectionSettings.token}`);
  return result;
}
/** Keep cancellation and the deadline active until the response body is consumed. */
export async function readResponseWithTimeout<T>(url: string | URL, init: RequestInit, read: (response: Response) => Promise<T>, timeout: number): Promise<T> {
  const controller = new AbortController();
  const external = init.signal;
  const abort = () => controller.abort(external?.reason);
  if (external?.aborted) abort();
  else external?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(() => controller.abort(new DOMException("后端请求超时，请检查服务连接", "TimeoutError")), timeout);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    const value = await read(await unwrap(response));
    controller.signal.throwIfAborted();
    return value;
  } catch (cause) {
    if (controller.signal.aborted) throw controller.signal.reason;
    throw cause;
  } finally {
    clearTimeout(timer);
    external?.removeEventListener("abort", abort);
  }
}
async function unwrap(response: Response) {
  if (response.ok) return response;
  let detail = `${response.status} ${response.statusText}`;
  try {
    const body = await response.json();
    detail = typeof body.detail === "string" ? body.detail : body.detail ? typeof body.detail.message === "string" ? body.detail.message : JSON.stringify(body.detail) : body.error || detail;
  } catch { /* A proxy error may be plain text. The request wrapper preserves abort reasons. */ }
  throw new Error(detail);
}
export const api = {
  get<T>(path: string, signal?: AbortSignal): Promise<T> {
    return readResponseWithTimeout(`${connectionSettings.base}${path}`, { headers: headers(), signal, cache: "no-store" }, (response) => response.json() as Promise<T>, 8000);
  },
  send<T>(path: string, body: unknown = {}, method = "POST", signal?: AbortSignal): Promise<T> {
    const form = body instanceof FormData;
    return readResponseWithTimeout(`${connectionSettings.base}${path}`, { method, signal, headers: headers(!form && method !== "DELETE"), body: method === "DELETE" ? undefined : form ? body : JSON.stringify(body) }, (response) => response.status === 204 ? Promise.resolve(undefined as T) : response.json() as Promise<T>, 45000);
  },
  async media(path: string, signal?: AbortSignal): Promise<Blob> {
    const backend = new URL(connectionSettings.base, window.location.origin);
    const url = new URL(path, backend.origin);
    if (url.origin !== backend.origin) throw new Error("媒体地址与后端不一致，已阻止发送认证信息");
    return readResponseWithTimeout(url, { headers: headers(), signal }, (response) => response.blob(), 45000);
  },
};
export const errorMessage = (error: unknown) => error instanceof Error ? error.message : "请求失败，请检查后端连接";
export const isAborted = (error: unknown) => error instanceof DOMException && error.name === "AbortError";

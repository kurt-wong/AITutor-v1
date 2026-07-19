/**
 * 共享 API 客户端
 * 
 * Phase 2 improvement: eliminates per-page fetch boilerplate.
 * All requests go through this client, which enforces:
 * - res.ok checking on every response
 * - centralized error handling
 * - JSON parsing
 */

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Default request timeout in milliseconds */
const DEFAULT_TIMEOUT_MS = 30_000;
/** Long timeout for batch upload / OCR processing */
export const LONG_TIMEOUT_MS = 300_000;

let _adminKey: string | null = null;

// 同步初始化：从 localStorage 加载 admin key，确保在 React 组件首次渲染前可用
try {
  const stored = localStorage.getItem("admin_key");
  if (stored) _adminKey = stored;
} catch {
  // localStorage 不可用（SSR / 安全限制）
}

export function setAdminKey(key: string) {
  _adminKey = key;
}

async function request<T>(
  url: string,
  options?: RequestInit,
  timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const headers: Record<string, string> = { ...(options?.headers as Record<string, string>) };
  if (_adminKey && url.includes("/api/admin/")) {
    headers["X-Admin-Key"] = _adminKey;
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, { ...options, headers, signal: controller.signal });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
        if (body.error?.message) detail = body.error.message;
      } catch {
        // ignore parse errors
      }
      throw new ApiError(detail, res.status);
    }

    const data = await res.json();
    return data as T;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError("请求超时，请检查网络后重试", 408);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** GET request, returns response body (not envelope.data). Returns data.data if present. */
export async function apiGet<T = unknown>(url: string): Promise<T> {
  const body = await request<{ data?: T } & Record<string, unknown>>(url);
  return (body.data ?? body) as T;
}

/** GET request with query params */
export async function apiGetParams<T = unknown>(
  path: string,
  params: Record<string, string | number | undefined>
): Promise<T> {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") search.set(k, String(v));
  }
  const qs = search.toString();
  const url = qs ? `${path}?${qs}` : path;
  return apiGet<T>(url);
}

/** POST request with JSON body */
export async function apiPost<T = unknown>(
  url: string,
  body?: unknown
): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: body != null ? { "Content-Type": "application/json" } : undefined,
    body: body != null ? JSON.stringify(body) : undefined,
  });
}

/** PUT request with JSON body — unwraps data envelope like apiGet */
export async function apiPut<T = unknown>(
  url: string,
  body?: unknown
): Promise<T> {
  const raw = await request<{ data?: T } & Record<string, unknown>>(url, {
    method: "PUT",
    headers: body != null ? { "Content-Type": "application/json" } : undefined,
    body: body != null ? JSON.stringify(body) : undefined,
  });
  return (raw.data ?? raw) as T;
}

/** POST with FormData */
export async function apiPostForm<T = unknown>(
  url: string,
  formData: FormData,
  timeoutMs?: number
): Promise<T> {
  return request<T>(url, { method: "POST", body: formData }, timeoutMs);
}

/** PUT with FormData */
export async function apiPutForm<T = unknown>(
  url: string,
  formData: FormData
): Promise<T> {
  return request<T>(url, { method: "PUT", body: formData });
}

/** DELETE request */
export async function apiDelete(url: string): Promise<void> {
  await request(url, { method: "DELETE" });
}

/** SSE streaming fetch — returns a ReadableStream reader */
export function sseConnect(url: string, options?: RequestInit): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  return fetch(url, options).then((res) => {
    if (!res.ok || !res.body) {
      throw new ApiError(`SSE connect failed: HTTP ${res.status}`, res.status);
    }
    return res.body.getReader();
  });
}

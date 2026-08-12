export type ApiError = {
  code: string;
  message: string;
  details?: Record<string, unknown> | null;
};

const DEFAULT_BASE = "http://localhost:8000";

/**
 * Resolve the API base URL. Primary env is NEXT_PUBLIC_API_URL; legacy
 * NEXT_PUBLIC_API_BASE is still honoured as a fallback, then localhost.
 */
export function apiBase(): string {
  return (
    process.env.NEXT_PUBLIC_API_URL ||
    process.env.NEXT_PUBLIC_API_BASE ||
    DEFAULT_BASE
  ).replace(/\/+$/, "");
}

/** Convert an http(s) API base into its ws counterpart for realtime sockets. */
export function wsHost(base: string = apiBase()): string {
  const origin =
    typeof window === "undefined" ? DEFAULT_BASE : window.location.origin;
  const url = new URL(base, origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/ws`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

type ApiOpts = {
  bearer?: string;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 10_000;

function buildUrl(path: string, query?: ApiOpts["query"]): string {
  const url = `${apiBase()}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function buildHeaders(opts: ApiOpts, json?: boolean): HeadersInit {
  const headers: HeadersInit = { ...(opts.headers || {}) };
  if (opts.bearer) headers["Authorization"] = `Bearer ${opts.bearer}`;
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    const candidate =
      body && typeof body === "object" && "error" in body
        ? (body as { error?: unknown }).error
        : null;
    const err: ApiError =
      candidate !== null &&
      typeof candidate === "object" &&
      "code" in candidate &&
      "message" in candidate &&
      typeof candidate.code === "string" &&
      typeof candidate.message === "string"
        ? { code: candidate.code, message: candidate.message }
        : {
            code: "http_error",
            message: res.statusText || `HTTP ${res.status}`,
          };
    const e = new Error(err.message) as Error & {
      status: number;
      api?: ApiError;
    };
    e.status = res.status;
    e.api = err;
    throw e;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

async function request<T>(
  path: string,
  init: RequestInit,
  opts: ApiOpts,
): Promise<T> {
  const controller = new AbortController();
  const onAbort = () => controller.abort(opts.signal?.reason);
  opts.signal?.addEventListener("abort", onAbort, { once: true });
  const timeout = globalThis.setTimeout(
    () =>
      controller.abort(new DOMException("Request timed out", "TimeoutError")),
    opts.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  try {
    const res = await fetch(buildUrl(path, opts.query), {
      ...init,
      signal: controller.signal,
    });
    return await handle<T>(res);
  } finally {
    globalThis.clearTimeout(timeout);
    opts.signal?.removeEventListener("abort", onAbort);
  }
}

export async function apiGet<T>(path: string, opts: ApiOpts = {}): Promise<T> {
  return request<T>(
    path,
    {
      headers: buildHeaders(opts),
    },
    opts,
  );
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  opts: ApiOpts = {},
): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: buildHeaders(opts, body !== undefined),
      body: body !== undefined ? JSON.stringify(body) : undefined,
    },
    opts,
  );
}

export { wsHost as wsUrl };

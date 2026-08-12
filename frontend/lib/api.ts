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
  // Backend upgrades at /ws (see backend/app/api/ws.py), not the bare host.
  return `${base.replace(/^http/, "ws")}/ws`;
}

type ApiOpts = {
  bearer?: string;
  query?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
};

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
    const err = (body && typeof body === "object" && "error" in body
      ? (body as { error: ApiError }).error
      : { code: "http_error", message: res.statusText }) as ApiError;
    const e = new Error(err.message) as Error & { status: number; api?: ApiError };
    e.status = res.status;
    e.api = err;
    throw e;
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export async function apiGet<T>(path: string, opts: ApiOpts = {}): Promise<T> {
  const res = await fetch(buildUrl(path, opts.query), {
    headers: buildHeaders(opts),
  });
  return handle<T>(res);
}

export async function apiPost<T>(
  path: string,
  body?: unknown,
  opts: ApiOpts = {}
): Promise<T> {
  const res = await fetch(buildUrl(path, opts.query), {
    method: "POST",
    headers: buildHeaders(opts, body !== undefined),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return handle<T>(res);
}

export { wsHost as wsUrl };

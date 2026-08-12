// Error helpers shared by client components.

export function errMsg(err: unknown): string {
  if (err instanceof Error) {
    const api = (err as Error & { api?: { code?: string; message?: string } }).api;
    if (api && typeof api === "object" && api.code && api.message) {
      return `${api.code} — ${api.message}`.trim();
    }
    return err.message;
  }
  return String(err);
}

export function isUnauthorized(err: unknown): boolean {
  return (
    err instanceof Error &&
    "status" in err &&
    (err as Error & { status?: number }).status === 401
  );
}

export type ActionError = { unauthorized: boolean; message: string };

export function toActionError(err: unknown): ActionError {
  return { unauthorized: isUnauthorized(err), message: errMsg(err) };
}

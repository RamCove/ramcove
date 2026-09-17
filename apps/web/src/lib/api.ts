/** API access. The browser always talks to the Next proxy at /api/*, which forwards the session cookie. */

export const API_ORIGIN = process.env.ROOM_API_ORIGIN ?? "http://127.0.0.1:8787";

export type ApiError = { code: string; message: string; reference?: string };

export class ApiFailure extends Error {
  constructor(
    public status: number,
    public error: ApiError,
  ) {
    super(error.message);
  }
}

/** Server-side fetch (React Server Components). Never cached: the queue and champion must be current. */
export async function apiGet<T>(path: string, cookie?: string): Promise<T> {
  const res = await fetch(`${API_ORIGIN}${path}`, {
    cache: "no-store",
    headers: cookie ? { cookie } : undefined,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiFailure(res.status, body.error ?? { code: "unreachable", message: "API unavailable" });
  }
  return body as T;
}

/** Server-side fetch that returns null instead of throwing, for optional panels. */
export async function apiGetOrNull<T>(path: string, cookie?: string): Promise<T | null> {
  try {
    return await apiGet<T>(path, cookie);
  } catch {
    return null;
  }
}

/** Browser fetch through the proxy. */
export async function clientFetch<T>(
  path: string,
  init?: RequestInit & { idempotencyKey?: string },
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.idempotencyKey) headers.set("idempotency-key", init.idempotencyKey);
  if (init?.body && !(init.body instanceof FormData)) headers.set("content-type", "application/json");
  const res = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiFailure(res.status, body.error ?? { code: "unreachable", message: "Request failed" });
  }
  return body as T;
}

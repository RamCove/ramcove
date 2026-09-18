/** Server-side reads for React Server Components. Kept apart from lib/api so the preview snapshot never
 *  ships in browser JavaScript. */

import snapshot from "@/preview/snapshot.json";
import { API_ORIGIN, ApiFailure } from "./api";
import { isPreview } from "./preview";

type Snapshot = { taken_at: string | null; source: string; responses: Record<string, unknown> };
const SNAPSHOT = snapshot as Snapshot;

export function snapshotTakenAt(): string | null {
  return SNAPSHOT.taken_at;
}

/** Never cached: the queue and champion must be current. In preview mode, answers from the snapshot. */
export async function apiGet<T>(path: string, cookie?: string): Promise<T> {
  if (isPreview()) {
    if (path in SNAPSHOT.responses) return SNAPSHOT.responses[path] as T;
    throw new ApiFailure(503, { code: "preview", message: "Not part of the public preview" });
  }
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

/** Returns null instead of throwing, for optional panels. */
export async function apiGetOrNull<T>(path: string, cookie?: string): Promise<T | null> {
  try {
    return await apiGet<T>(path, cookie);
  } catch {
    return null;
  }
}

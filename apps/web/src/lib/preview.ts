/**
 * Public preview mode.
 *
 * The full product needs the Python API, PostgreSQL and the workers. A static host such as Vercel runs
 * only this web app, so without an API origin it serves a labelled snapshot of the local demo instead:
 * the pages render from recorded API responses, marked as a snapshot rather than live.
 *
 * On by default on Vercel unless a real API origin is configured; RAMCOVE_PREVIEW=1 forces it anywhere.
 */
export function isPreview(): boolean {
  if (process.env.RAMCOVE_PREVIEW === "1") return true;
  if (process.env.RAMCOVE_PREVIEW === "0") return false;
  return process.env.VERCEL === "1" && !process.env.RAMCOVE_API_ORIGIN;
}

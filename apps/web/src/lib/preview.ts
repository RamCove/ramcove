/**
 * Public preview mode.
 *
 * The full product needs the Python API, PostgreSQL and the workers. A static host such as Vercel runs
 * only this web app, so there it serves a labelled, read-only snapshot of the local demo instead:
 * public pages render from recorded API responses, and sign-in, submitting and every write are off.
 * That also keeps the demo identities, whose keys are published, off the public internet.
 *
 * On by default on Vercel unless a real API origin is configured; RAMCOVE_PREVIEW=1 forces it anywhere.
 */
export function isPreview(): boolean {
  if (process.env.RAMCOVE_PREVIEW === "1") return true;
  if (process.env.RAMCOVE_PREVIEW === "0") return false;
  return process.env.VERCEL === "1" && !process.env.RAMCOVE_API_ORIGIN;
}

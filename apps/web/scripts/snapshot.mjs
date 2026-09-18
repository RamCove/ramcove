/**
 * Record the public API responses the site needs, for the read-only public preview.
 *
 *   ROOM_API_ORIGIN=http://127.0.0.1:8787 node scripts/snapshot.mjs
 *
 * Only public routes are read, with no session, so nothing private can be captured. The file is
 * refused if anything that looks like a secret appears in it.
 */
import { writeFile } from "node:fs/promises";

const API = process.env.ROOM_API_ORIGIN ?? "http://127.0.0.1:8787";
const OUT = new URL("../src/preview/snapshot.json", import.meta.url);

const FIXED = ["/v1/meta", "/v1/overview", "/v1/profile", "/v1/status", "/v1/demo/fixtures"];
const QUEUE_KINDS = ["admitted", "waiting", "history"];
const MAX_QUEUE_PAGES = 3;

async function get(path) {
  const res = await fetch(API + path, { headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${path} answered ${res.status}`);
  return res.json();
}

const responses = {};
for (const path of FIXED) responses[path] = await get(path);

const submissionIds = new Set();
for (const kind of QUEUE_KINDS) {
  let cursor = null;
  for (let page = 0; page < MAX_QUEUE_PAGES; page++) {
    // must match how the queue page builds its query string: kind first, then cursor
    const qs = new URLSearchParams({ kind, ...(cursor ? { cursor } : {}) });
    const path = `/v1/queue?${qs}`;
    const body = await get(path);
    responses[path] = body;
    for (const item of body.items ?? []) if (item.submission_id) submissionIds.add(item.submission_id);
    cursor = body.next_cursor;
    if (!cursor) break;
  }
}
for (const id of submissionIds) responses[`/v1/submissions/${id}`] = await get(`/v1/submissions/${id}`);

const snapshot = {
  taken_at: new Date().toISOString(),
  source: `public routes of the local demo simulation at ${new URL(API).host}`,
  responses,
};
const text = JSON.stringify(snapshot, null, 1) + "\n";

// Refuse anything that looks like a credential or a private key, even though only public routes are read.
const forbidden = [/ghp_[A-Za-z0-9]{20,}/, /github_pat_/, /PRIVATE KEY/, /\/\/Room[A-Z]\w*/, /password/i, /postgres(ql)?:\/\//i, /set-cookie/i];
for (const re of forbidden) {
  if (re.test(text)) {
    console.error(`refusing to write the snapshot: it matches ${re}`);
    process.exit(1);
  }
}
await writeFile(OUT, text);
console.log(`snapshot: ${Object.keys(responses).length} responses, ${submissionIds.size} submissions, ${(text.length / 1024).toFixed(1)} KiB`);

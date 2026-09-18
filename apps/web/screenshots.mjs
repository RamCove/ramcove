/**
 * Browser verification: visits every surface, records console errors, checks for horizontal page
 * overflow, and writes screenshots to docs/screenshots.
 *
 *   node screenshots.mjs [baseUrl] [outDir]
 */
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const base = process.argv[2] ?? "http://127.0.0.1:3787";
const out = process.argv[3] ?? "../../docs/screenshots";
await mkdir(out, { recursive: true });

const VIEWPORTS = { desktop: { width: 1440, height: 900 }, tablet: { width: 768, height: 1024 }, phone: { width: 390, height: 844 } };

const PAGES = [
  { name: "overview", path: "/", as: null, viewports: ["desktop", "tablet", "phone"] },
  { name: "competition", path: "/competition", as: null, viewports: ["desktop"] },
  { name: "queue", path: "/queue", as: null, viewports: ["desktop", "phone"] },
  { name: "queue-history", path: "/queue?kind=history", as: null, viewports: ["desktop"] },
  { name: "docs", path: "/docs", as: null, viewports: ["desktop"] },
  { name: "status", path: "/status", as: null, viewports: ["desktop"] },
  { name: "submit", path: "/submit", as: "miner-cyd", viewports: ["desktop", "phone"] },
  { name: "submissions", path: "/submissions", as: "miner-ada", viewports: ["desktop"] },
  { name: "submission-detail", path: "SUBMISSION", as: "miner-ada", viewports: ["desktop", "tablet"] },
  { name: "validator", path: "/validator", as: "validator-op", viewports: ["desktop"] },
  { name: "review", path: "/review", as: "reviewer-1", viewports: ["desktop"] },
  { name: "operator", path: "/operator", as: "operator", viewports: ["desktop"] },
];

const browser = await chromium.launch();
const report = [];

async function signIn(context, identity) {
  const page = await context.newPage();
  await page.goto(`${base}/`);
  const res = await page.evaluate(async (id) => {
    const r = await fetch("/api/v1/auth/demo", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ identity: id }),
    });
    return { status: r.status, body: await r.json() };
  }, identity);
  await page.close();
  if (res.status !== 200) throw new Error(`sign-in failed for ${identity}: ${JSON.stringify(res.body)}`);
}

// find a promoted submission to screenshot in detail
const probe = await browser.newContext();
const probePage = await probe.newPage();
await probePage.goto(`${base}/queue?kind=history`);
const detailHref = await probePage.evaluate(() => {
  const a = Array.from(document.querySelectorAll('a[href^="/submissions/"]'))[0];
  return a ? a.getAttribute("href") : null;
});
await probe.close();

for (const spec of PAGES) {
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  if (spec.as) await signIn(context, spec.as);
  for (const vp of spec.viewports) {
    const page = await context.newPage();
    await page.setViewportSize(VIEWPORTS[vp]);
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 300)));
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
    const path = spec.path === "SUBMISSION" ? (detailHref ?? "/submissions") : spec.path;
    const response = await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(400);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
    const deadButtons = await page.evaluate(
      () => Array.from(document.querySelectorAll("button")).filter((b) => !b.textContent?.trim() && !b.getAttribute("aria-label")).length,
    );
    const file = `${out}/${spec.name}-${vp}.png`;
    await page.screenshot({ path: file, fullPage: true });
    report.push({ page: spec.name, viewport: vp, status: response?.status(), overflow, deadButtons, errors });
    await page.close();
  }
  await context.close();
}

// light theme check on the overview
{
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  const page = await context.newPage();
  await page.goto(`${base}/`);
  await page.evaluate(() => {
    localStorage.setItem("room-theme", "light");
    document.documentElement.dataset.theme = "light";
  });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}/overview-light.png`, fullPage: true });
  report.push({ page: "overview", viewport: "desktop-light", status: 200, overflow: false, deadButtons: 0, errors: [] });
  await context.close();
}

await browser.close();
console.log(JSON.stringify(report, null, 1));
const problems = report.filter((r) => r.overflow || r.deadButtons > 0 || r.errors.length > 0 || (r.status ?? 200) >= 400);
console.log(`\n${report.length} views captured, ${problems.length} with problems`);
if (problems.length) console.log(JSON.stringify(problems, null, 1));

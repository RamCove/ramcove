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
  { name: "overview", path: "/", viewports: ["desktop", "tablet", "phone"] },
  { name: "dashboard", path: "/dashboard", viewports: ["desktop", "phone"] },
  { name: "docs", path: "/docs", viewports: ["desktop", "phone"] },
  { name: "docs-rules", path: "/docs/rules", viewports: ["desktop"] },
  { name: "status", path: "/status", viewports: ["desktop"] },
  { name: "submission-detail", path: "SUBMISSION", viewports: ["desktop", "tablet"] },
];

const browser = await chromium.launch();
const report = [];

// find a promoted submission to screenshot in detail
const probe = await browser.newContext();
const probePage = await probe.newPage();
await probePage.goto(`${base}/dashboard`);
const detailHref = await probePage.evaluate(() => {
  const a = Array.from(document.querySelectorAll('a[href^="/submissions/"]'))[0];
  return a ? a.getAttribute("href") : null;
});
await probe.close();

for (const spec of PAGES) {
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  for (const vp of spec.viewports) {
    const page = await context.newPage();
    await page.setViewportSize(VIEWPORTS[vp]);
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 300)));
    page.on("pageerror", (e) => errors.push(String(e).slice(0, 300)));
    const path = spec.path === "SUBMISSION" ? (detailHref ?? "/dashboard") : spec.path;
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

// dark theme check on the overview (light is the default)
{
  const context = await browser.newContext({ viewport: VIEWPORTS.desktop });
  await context.addInitScript(() => {
    try {
      localStorage.setItem("ramcove-theme", "dark");
    } catch {}
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 300)));
  const response = await page.goto(`${base}/`, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  await page.screenshot({ path: `${out}/overview-dark.png`, fullPage: true });
  if (theme !== "dark") errors.push(`expected the dark theme, got ${theme}`);
  report.push({ page: "overview", viewport: "desktop-dark", status: response?.status(), overflow, deadButtons: 0, errors });
  await context.close();
}

await browser.close();
console.log(JSON.stringify(report, null, 1));
const problems = report.filter((r) => r.overflow || r.deadButtons > 0 || r.errors.length > 0 || (r.status ?? 200) >= 400);
console.log(`\n${report.length} views captured, ${problems.length} with problems`);
if (problems.length) console.log(JSON.stringify(problems, null, 1));

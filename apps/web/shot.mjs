import { chromium } from "@playwright/test";
const [url, out, w = 1440, h = 900, theme = "dark"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: +w, height: +h } });
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(url, { waitUntil: "networkidle" });
if (theme === "light") { await page.evaluate(() => { localStorage.setItem("room-theme", "light"); document.documentElement.dataset.theme = "light"; }); await page.waitForTimeout(300); }
await page.screenshot({ path: out, fullPage: true });
const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
console.log(JSON.stringify({ out, title: await page.title(), overflow, errors }));
await browser.close();

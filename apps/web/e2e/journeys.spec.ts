import { expect, request, test, type Page } from "@playwright/test";

const API = process.env.RAMCOVE_API_ORIGIN ?? "http://127.0.0.1:8787";
const PDF = "/whitepaper/RamCove_Whitepaper_v0.2.pdf";

function consoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

/** Miners submit from the command line, so tests create work through the local API the same way. */
async function submitAsMiner(identity: string, fixture: string) {
  const api = await request.newContext({ baseURL: API });
  expect((await api.post("/v1/auth/demo", { data: { identity } })).status()).toBe(200);
  const r = await api.post("/v1/demo/submit-fixture", { data: { fixture } });
  const body = await r.json();
  await api.dispose();
  return { status: r.status(), body };
}

test("a visitor understands the competition, with nothing to sign in to", async ({ page }) => {
  const errors = consoleErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Same GPU");
  await expect(page.getByText(/serve more useful AI requests/).first()).toBeVisible();
  // no banner, but every page says which mode it is running in
  await expect(page.getByText(/running in simulation mode/i).first()).toBeVisible();
  // the site is read-only: miners use the command line and validators run ramcove-validator
  await expect(page.getByRole("button", { name: /sign in/i })).toHaveCount(0);
  const header = page.getByRole("banner");
  await expect(header.getByRole("link", { name: "Submit" })).toHaveCount(0);
  // the header opens the whitepaper and the repository in new tabs
  await expect(header.getByRole("link", { name: "Whitepaper (PDF)" })).toHaveAttribute("href", PDF);
  await expect(header.getByRole("link", { name: "RamCove on GitHub" })).toHaveAttribute(
    "href",
    "https://github.com/RamCove/ramcove",
  );
  const bar = page.getByRole("navigation", { name: "Main" });
  if (await bar.isVisible()) {
    await bar.getByRole("link", { name: "Dashboard" }).click();
  } else {
    // phones: the menu sits behind the menu button
    await page.getByRole("button", { name: "Menu" }).click();
    await page.getByRole("navigation", { name: "Main (compact)" }).getByRole("link", { name: "Dashboard" }).click();
  }
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();
  await expect(page.getByText("Current champion")).toBeVisible();
  await page.goto("/");
  await page.getByRole("link", { name: "Read the rules" }).first().click();
  await expect(page).toHaveURL(/\/docs\/rules/);
  await expect(page.getByText("How a challenger replaces the champion")).toBeVisible();
  await expect(page.getByText(/rule hash/i).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("the docs show miners and validators how to take part from the command line", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Start mining" }).first().click();
  await expect(page).toHaveURL(/\/docs#miners/);
  await expect(page.getByRole("heading", { name: "Submit from the command line" })).toBeVisible();
  await expect(page.getByText(/ramcove-miner submit --artifact/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Run the validator software" })).toBeVisible();
  await expect(page.getByText(/uv run ramcove-worker/)).toBeVisible();
});

test("the whitepaper opens full screen as a PDF", async ({ page }) => {
  await page.goto("/docs");
  const tab = page.getByRole("navigation", { name: "Documentation" }).getByRole("link", { name: "Whitepaper" });
  await expect(tab).toHaveAttribute("href", PDF);
  await expect(tab).toHaveAttribute("target", "_blank");
  const pdf = await page.request.get(PDF);
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()["content-type"]).toContain("application/pdf");
  // the old embedded page now goes straight to the PDF
  const old = await page.request.get("/docs/whitepaper", { maxRedirects: 0 });
  expect(old.status()).toBe(307);
  expect(old.headers()["location"]).toBe(PDF);
});

test("the dashboard shows the order of work; retired pages land where their content lives", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page.getByText("Paid, in the order they are tested")).toBeVisible();
  await expect(page.getByText("Free, waiting for capacity")).toBeVisible();
  await expect(page.getByText("Order of work versus order of promotion")).toBeVisible();
  const moved: [string, RegExp][] = [
    ["/queue", /\/dashboard/],
    ["/competition", /\/docs\/rules/],
    ["/submit", /\/docs#miners/],
    ["/submissions", /\/dashboard/],
    ["/validator", /\/docs#validators/],
    ["/review", /\/dashboard/],
    ["/operator", /\/status/],
  ];
  for (const [from, to] of moved) {
    await page.goto(from);
    await expect(page).toHaveURL(to);
  }
  await page.goto("/competition");
  const tabs = page.getByRole("navigation", { name: "Documentation" });
  await expect(tabs.getByRole("link", { name: "Rules" })).toHaveAttribute("aria-current", "page");
});

test("anyone can follow a submission on its public page", async ({ page }) => {
  // make sure there is at least one; a fixture this database has already seen is refused as a duplicate
  for (const fixture of ["fragmentation-aware-allocator", "kv8-conversation-retention", "evict-quarter"]) {
    const r = await submitAsMiner("miner-ada", fixture);
    if (r.status === 200 && r.body.ok) break;
  }
  await page.goto("/dashboard");
  const first = page.locator('a[href^="/submissions/sub_"]').first();
  await expect(first).toBeVisible();
  await first.click();
  await page.waitForURL(/\/submissions\/sub_/);
  await expect(page.getByRole("heading", { name: "Submission", exact: true })).toBeVisible();
  await expect(page.getByText("Progress")).toBeVisible();
  await expect(page.getByText(/Support ref RM-/)).toBeVisible();
  await expect(page.getByText("What the states mean")).toBeVisible();
  // the author's payment details are never on the public page
  await expect(page.getByText("Your payment")).toHaveCount(0);
});

test("keyboard users can reach the main actions and both themes are readable", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  for (let i = 0; i < 6; i++) await page.keyboard.press("Tab");
  const focusVisible = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    const style = getComputedStyle(el);
    return style.boxShadow !== "none" || style.outlineStyle !== "none";
  });
  expect(focusVisible).toBe(true);
  // light is the default; the toggle must switch to the other theme and back
  const before = await page.locator("html").getAttribute("data-theme");
  const after = before === "dark" ? "light" : "dark";
  await page.getByRole("button", { name: /theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", after);
  const contrast = await page.evaluate(() => {
    const body = getComputedStyle(document.body);
    return { bg: body.backgroundColor, color: body.color };
  });
  expect(contrast.bg).not.toBe(contrast.color);
});

test("an unknown page explains itself instead of failing", async ({ page }) => {
  const response = await page.goto("/does-not-exist");
  expect(response?.status()).toBe(404);
  await expect(page.getByText("That page does not exist")).toBeVisible();
});

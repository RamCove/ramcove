import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page, identity: string) {
  await page.goto("/");
  const res = await page.evaluate(async (id) => {
    const r = await fetch("/api/v1/auth/demo", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ identity: id }),
    });
    return r.status;
  }, identity);
  expect(res).toBe(200);
  await page.reload();
}

/** Withdraw any active submission so the miner journey starts from a known state. */
async function clearActiveSubmissions(page: Page) {
  const result = await page.evaluate(async () => {
    const mine = await (await fetch("/api/v1/miner/submissions")).json();
    const active = (mine.items ?? []).filter(
      (s: { state: string }) =>
        ![
          "promoted",
          "not_promoted",
          "rejected_preflight",
          "rejected_screen",
          "review_rejected",
          "expired_quote",
          "expired_unregistered",
          "operator_failed",
          "withdrawn",
        ].includes(s.state),
    );
    const outcomes: number[] = [];
    for (const s of active) {
      const r = await fetch(`/api/v1/miner/submissions/${s.submission_id}/withdraw`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reason: "browser test reset" }),
      });
      outcomes.push(r.status);
    }
    return { listed: (mine.items ?? []).length, active: active.length, outcomes };
  });
  expect(result.outcomes.every((s) => s === 200), `cleanup failed: ${JSON.stringify(result)}`).toBe(true);
  return result;
}

function consoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  return errors;
}

test("a visitor understands the competition without signing in", async ({ page }) => {
  const errors = consoleErrors(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("more useful AI requests");
  await expect(page.getByText("Local development build")).toBeVisible();
  await expect(page.getByRole("link", { name: "Start a submission" })).toBeVisible();
  await page.getByRole("link", { name: "Explore the competition" }).click();
  await expect(page).toHaveURL(/\/competition/);
  await expect(page.getByText("How a challenger replaces the champion")).toBeVisible();
  await expect(page.getByText(/rule hash/i).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("the queue separates paid admissions from the free waiting list", async ({ page }) => {
  await page.goto("/queue");
  await expect(page.getByRole("link", { name: "Waiting list (free)" })).toBeVisible();
  await page.getByRole("link", { name: "Finished" }).click();
  await expect(page).toHaveURL(/kind=history/);
  await expect(page.getByText("Order of work versus order of promotion")).toBeVisible();
});

test("a miner sees the fee before signing and can recover an existing payment", async ({ page }) => {
  await signIn(page, "miner-cyd");
  await clearActiveSubmissions(page);
  await page.goto("/submit");
  await expect(page.getByText("Which checks are free and which consume the fee")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();
  // Duplicate detection is real: pick a fixture this database has not seen yet.
  const build = page.getByRole("button", { name: "Build, sign and run free checks" });
  await expect(build).toBeEnabled({ timeout: 15_000 });
  const fixtures = page.getByRole("radio");
  const count = await fixtures.count();
  let accepted = false;
  for (let i = 0; i < count; i++) {
    await fixtures.nth(i).check();
    await build.click();
    const result = page.getByRole("heading", { name: /^Free checks (passed|found problems)$/ });
    const alert = page.getByRole("alert");
    await expect(result.or(alert).first()).toBeVisible({ timeout: 30_000 });
    if (await result.isVisible()) {
      if ((await result.textContent())?.includes("passed")) {
        accepted = true;
        break;
      }
    }
    // a duplicate, an active lineage or another refusal: try the next fixture
    await page.getByRole("button", { name: "2. Prepare" }).click();
  }
  expect(accepted, "at least one fixture should pass the free checks").toBe(true);
  await page.getByRole("button", { name: "Reserve evaluation capacity" }).click();
  await expect(page.getByText("Quote and payment").first()).toBeVisible({ timeout: 30_000 });
  // either a quote with the amount and rules, or an honest message explaining why there is none
  const quotePanel = page.getByText("What you are signing");
  const waitPanel = page.getByText(/waiting list|capacity|paused/i).first();
  await expect(quotePanel.or(waitPanel).first()).toBeVisible({ timeout: 30_000 });
  const hasQuote = await quotePanel.isVisible();
  if (hasQuote) {
    await expect(page.getByText(/Recipient \(evaluation wallet\)/)).toBeVisible();
    await expect(page.getByText(/Network transaction fee/)).toBeVisible();
    await expect(page.getByText(/Refund rules for this quote/)).toBeVisible();
    await page.getByRole("button", { name: /Sign and pay/ }).click();
    await expect(page.getByRole("heading", { name: "Authorize this simulated payment" })).toBeVisible();
    await page.getByRole("button", { name: "Cancel" }).click();
  } else {
    await expect(waitPanel).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "Already paid? Recover by reference" })).toBeVisible();
});

test("a miner can follow a submission and read why it ended", async ({ page }) => {
  await signIn(page, "miner-ada");
  await clearActiveSubmissions(page);
  // create one, so the test does not depend on what an earlier run left behind
  const created = await page.evaluate(async () => {
    const r = await fetch("/api/v1/demo/submit-fixture", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ fixture: "fragmentation-aware-allocator" }),
    });
    return { status: r.status, body: await r.json() };
  });
  expect(created.status, JSON.stringify(created.body)).toBe(200);
  await page.goto("/submissions");
  const first = page.locator('a[href^="/submissions/sub_"]').first();
  await expect(first).toBeVisible();
  await first.click();
  await page.waitForURL(/\/submissions\/sub_/);
  await expect(page.getByRole("heading", { name: "Submission", exact: true })).toBeVisible();
  await expect(page.getByText("Progress")).toBeVisible();
  await expect(page.getByText(/Support ref RM-/)).toBeVisible();
  await expect(page.getByText("What the states mean")).toBeVisible();
});

test("roles are enforced in the interface and on the server", async ({ page }) => {
  await signIn(page, "miner-bao");
  await page.goto("/operator");
  await expect(page.getByText("Sign in as the operator")).toBeVisible();
  const status = await page.evaluate(async () => (await fetch("/api/v1/operator/console")).status);
  expect(status).toBe(403);
});

test("the operator console shows guardrails and verifies the audit chain", async ({ page }) => {
  await signIn(page, "operator");
  await page.goto("/operator");
  await expect(page.getByText("No route sets a champion by hand.")).toBeVisible();
  await page.getByRole("button", { name: "Verify the audit chain" }).click();
  await expect(page.getByText("audit chain intact")).toBeVisible({ timeout: 15_000 });
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
  await page.getByRole("button", { name: /theme/i }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
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

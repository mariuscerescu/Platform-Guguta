/** Run only against an isolated survey database, never the public server. */
import { expect, test } from "@playwright/test";

const BASE = process.env.GUGUTA_E2E_BASE_PATH ?? "";
const API = `${BASE}/guguta-api/api/v1/survey`;
test.skip(process.env.GUGUTA_SURVEY_E2E !== "isolated", "Requires an isolated, disposable survey database.");

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("guguta.cookie-notice.v1", "seen"));
});

test("twenty questions, a failed send and a retry persist one anonymous response", async ({ page, context }) => {
  await context.addCookies([{ name: "guguta_session", value: "must-not-be-sent", domain: "127.0.0.1", path: "/" }]);
  const requests: string[] = [];
  page.on("request", request => {
    if (request.url().includes("/api/v1/survey")) {
      expect(request.headers()["cookie"]).toBeUndefined();
      requests.push(request.url());
    }
  });
  await page.goto(`${BASE}/sondaj`);
  await expect(page.getByRole("heading", { name: "Părerea ta despre Guguță" })).toBeVisible();
  await expect(page.getByText("20 de întrebări", { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("survey-intro.png") });
  await page.getByRole("button", { name: "Începe sondajul" }).click();
  for (let i = 1; i <= 20; i++) {
    await expect(page.locator(".survey-progress-label strong")).toHaveText(`${i} / 20`);
    if (i <= 18) await page.locator(".survey-option input").first().check();
    if (i === 6) await page.screenshot({ path: test.info().outputPath("survey-question.png") });
    if (i === 19) await page.getByRole("textbox").fill("Explicații clare (răspuns fictiv de test).");
    if (i === 20) await page.getByRole("textbox").fill("<script>window.surveyUnsafe=true</script>");
    if (i < 20) await page.getByRole("button", { name: "Continuă" }).click();
  }
  await expect(page.locator(".survey-progress-label strong")).toHaveText("20 / 20");
  const send = page.getByRole("button", { name: "Trimite răspunsurile" });
  await expect(send).toBeEnabled();
  let first = true;
  await page.route(`**/api/v1/survey/responses`, async route => {
    if (first) { first = false; return route.fulfill({ status: 503, json: { message: "Eroare temporară de test." } }); }
    return route.continue();
  });
  await send.click();
  await expect(page.getByRole("alert").filter({ hasText: "Eroare temporară" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Mulțumim pentru părerea ta!" })).toHaveCount(0);
  const saved = page.waitForResponse(response => response.url().endsWith("/survey/responses") && response.status() === 201);
  await send.click();
  await saved;
  await expect(page.getByRole("heading", { name: "Mulțumim pentru părerea ta!" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Mulțumim pentru părerea ta!" })).toBeVisible();
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem("guguta.survey.draft.v1") || "{}").answers)).toBeUndefined();
  const result = await page.request.get(`${API}/results`);
  expect((await result.json()).total).toBe(1);
  expect(requests.some(url => url.endsWith("/survey/responses"))).toBe(true);
});

test("public results contain the written opinions as text and export successfully", async ({ page }) => {
  await page.goto(`${BASE}/sondaj/rezultate`);
  await expect(page.locator(".survey-results-total strong")).toHaveText("1");
  await expect(page.locator(".survey-result-card")).toHaveCount(20);
  await expect(page.getByText("Explicații clare (răspuns fictiv de test).", { exact: true })).toBeVisible();
  await expect(page.getByText("<script>window.surveyUnsafe=true</script>", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => "surveyUnsafe" in window)).toBe(false);
  await page.screenshot({ path: test.info().outputPath("survey-results.png") });
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("link", { name: "Descarcă rezultatele (CSV)" }).click()]);
  expect(download.suggestedFilename()).toBe("guguta-sondaj-rezultate.csv");
});

test("phone layout and draft restoration keep the selected answer", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${BASE}/sondaj`);
  await page.getByRole("button", { name: "Mărește codul QR pentru sondaj" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("link")).toHaveAttribute("href", "https://tineri.math.md/edu-platform/sondaj");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Începe sondajul" }).click();
  await page.getByLabel("Clasa V", { exact: true }).check();
  await page.reload();
  await expect(page.getByLabel("Clasa V", { exact: true })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("survey-phone.png") });
});

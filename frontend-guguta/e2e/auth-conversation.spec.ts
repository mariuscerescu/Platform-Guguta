/**
 * E2E Guguță — înregistrarea ca o conversație cu Guguță, informarea despre
 * cookie-uri și pagina „Contul meu”.
 *
 * Stack-ul E2E rulează cu autentificare de test (dev-login), deci
 * /auth/config și /auth/register sunt simulate cu `page.route`; restul paginii
 * (layout, componente, validări) este real.
 *
 * Rulare: cd frontend-guguta && npx playwright test e2e/auth-conversation.spec.ts
 */
import { expect, test } from "@playwright/test";

test.describe("Înregistrare conversațională", () => {
  test("Guguță întreabă, elevul răspunde, fișa se completează, acordurile se cer, parola la final", async ({ page }) => {
    const bodies: Array<Record<string, unknown>> = [];
    await page.route("**/guguta-api/api/v1/auth/config", (route) =>
      route.fulfill({ json: { auth_mode: "password", privacy_version: "2026-10-21" } }),
    );
    await page.route("**/guguta-api/api/v1/auth/register", (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: { id: "u1", display_name: "Ana Popescu", roles: ["user"] }, headers: { "X-Guguta-CSRF": "csrf" } });
    });
    await page.route("**/guguta-api/api/v1/auth/me", (route) => route.fulfill({ status: 401, json: {} }));
    await page.route("**/guguta-api/api/v1/notebooks**", (route) => route.fulfill({ json: [] }));
    await page.route("**/guguta-api/api/v1/catalog/**", (route) => route.fulfill({ json: [] }));

    await page.goto("/register");
    await expect(page.getByRole("heading", { name: "Hai să-ți facem cont" })).toBeVisible();
    const log = page.getByRole("log", { name: "Conversația cu Guguță" });
    await expect(log).toContainText("Cum te cheamă?");

    const answer = page.locator("#talk-answer");
    await answer.fill("A");
    await answer.press("Enter");
    await expect(page.getByRole("alert")).toContainText("prea scurt");
    await answer.fill("Ana");
    await answer.press("Enter");
    await expect(log).toContainText("Încântat, Ana!");
    await answer.fill("Popescu");
    await answer.press("Enter");
    await answer.fill("Liceul Teoretic „Ion Creangă”, Bălți");
    await answer.press("Enter");
    await expect(log).toContainText("În ce clasă ești?");
    await page.getByRole("group", { name: "Clasa" }).getByRole("button", { name: "V", exact: true }).click();
    await expect(log).toContainText("acordul unui părinte");

    await answer.fill("ana@exemplu");
    await answer.press("Enter");
    await expect(page.getByRole("alert")).toContainText("e-mail");
    await answer.fill("ana@exemplu.md");
    await answer.press("Enter");

    // Acordul părintelui (clasa a V-a) și politica de confidențialitate.
    await expect(log).toContainText("părinte sau un tutore");
    await page.getByRole("button", { name: "Da, este de acord" }).click();
    await expect(log).toContainText("Ești de acord?");
    await expect(page.getByRole("link", { name: "Politica de confidențialitate" }).first()).toHaveAttribute("href", /confidentialitate/);
    await page.getByRole("button", { name: "Sunt de acord" }).click();

    // Recapitulare: corectăm școala, apoi confirmăm.
    await expect(log).toContainText("nu am introdus nicio greșeală?");
    const sheet = page.getByRole("complementary", { name: "Fișa ta" });
    await expect(sheet).toContainText("Ana");
    await expect(sheet).toContainText("a V-a");
    await page.locator(".talk-review li", { hasText: "Școala" }).getByRole("button", { name: "Corectează" }).click();
    await answer.fill("Liceul Teoretic „Mihai Eminescu”, Bălți");
    await answer.press("Enter");
    await expect(log).toContainText("nu am introdus nicio greșeală?");
    await expect(sheet).toContainText("Mihai Eminescu");
    await page.getByRole("button", { name: "Totul e corect" }).click();

    // Parola: nu apare în transcript, trebuie confirmată.
    await expect(log).toContainText("cheia de la dulapul tău virtual");
    await expect(answer).toHaveAttribute("type", "password");
    await answer.fill("parola-mea-123");
    await answer.press("Enter");
    await answer.fill("altceva");
    await answer.press("Enter");
    await expect(page.getByRole("alert")).toContainText("nu coincid");
    await answer.fill("parola-mea-123");
    await Promise.all([page.waitForURL("**/app"), answer.press("Enter")]);
    await expect(log).not.toContainText("parola-mea-123");

    expect(bodies).toEqual([{
      first_name: "Ana", last_name: "Popescu", email: "ana@exemplu.md", password: "parola-mea-123",
      school: "Liceul Teoretic „Mihai Eminescu”, Bălți", class_level: "V", privacy_accepted: true, parent_consent: true,
    }]);
  });

  test("informarea despre cookie-uri apare o singură dată și duce la politică", async ({ page }) => {
    await page.goto("/");
    const notice = page.getByRole("region", { name: "Informare despre cookie-uri" });
    await expect(notice).toContainText("strict necesare");
    await notice.getByRole("link", { name: "Politica de confidențialitate" }).click();
    await expect(page.getByRole("heading", { name: "Politica de confidențialitate" })).toBeVisible();
    await page.getByRole("button", { name: "Am înțeles" }).click();
    await expect(notice).toBeHidden();
    await page.reload();
    await expect(page.getByRole("region", { name: "Informare despre cookie-uri" })).toHaveCount(0);
  });

  test("pagina Contul meu cere autentificare când nu există sesiune", async ({ page }) => {
    await page.goto("/cont");
    await expect(page.getByText("Nu ești autentificat.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Intră în cont" })).toHaveAttribute("href", /login/);
  });
});

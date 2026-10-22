/**
 * E2E Guguță — formularul clasic de înregistrare și alegerea instituției, informarea despre
 * cookie-uri și pagina „Contul meu”.
 *
 * Stack-ul E2E rulează cu autentificare de test (dev-login), deci
 * /auth/config și /auth/register sunt simulate cu `page.route`; restul paginii
 * (layout, componente, validări) este real.
 *
 * Rulare: cd frontend-guguta && npx playwright test e2e/auth-conversation.spec.ts
 */
import { expect, test } from "@playwright/test";

test.describe("Înregistrare clasică", () => {
  test("alegerea instituției, validarea parolelor și acordurile trimit profilul complet", async ({ page }) => {
    const bodies: Array<Record<string, unknown>> = [];
    await page.route("**/guguta-api/api/v1/auth/config", (route) =>
      route.fulfill({ json: { auth_mode: "password", privacy_version: "2026-10-22" } }),
    );
    await page.route("**/schools-md.json", (route) => route.fulfill({ json: { schools: [
      { name: "Instituția Publică Liceul Teoretic „M. Eminescu”", locality: "MUN.BĂLȚI", district: "BĂLȚI" },
      { name: "Instituția Publică Liceul Teoretic „Mihai Eminescu”", locality: "MUN.CHIȘINĂU", district: "CHIȘINĂU" },
    ] } }));
    await page.route("**/guguta-api/api/v1/auth/register", (route) => {
      bodies.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({ json: { id: "u1", display_name: "Ana Popescu", roles: ["user"] }, headers: { "X-Guguta-CSRF": "csrf" } });
    });
    await page.route("**/guguta-api/api/v1/auth/me", (route) => route.fulfill({ status: 401, json: {} }));
    await page.route("**/guguta-api/api/v1/notebooks**", (route) => route.fulfill({ json: [] }));
    await page.route("**/guguta-api/api/v1/catalog/**", (route) => route.fulfill({ json: [] }));

    await page.goto("/register");
    await page.getByRole("button", { name: "Am înțeles" }).click();
    await expect(page.getByRole("heading", { name: "Creează contul Guguță" })).toBeVisible();
    await expect(page.getByRole("log")).toHaveCount(0);
    await page.getByLabel("Prenume", { exact: true }).fill("Ana");
    await page.getByLabel("Nume", { exact: true }).fill("Popescu");
    const school = page.getByRole("combobox", { name: "Școală / liceu / instituție" });
    await school.fill("eminescu balti");
    await expect(page.getByRole("listbox", { name: "Instituții de învățământ" }).getByRole("option")).toHaveCount(1);
    await school.press("ArrowDown");
    await school.press("Enter");
    await expect(school).toHaveValue("Instituția Publică Liceul Teoretic „M. Eminescu” (MUN.BĂLȚI, BĂLȚI)");
    await expect(page.getByRole("listbox")).toHaveCount(0);
    await page.getByLabel("Clasa", { exact: true }).selectOption("V");
    await page.getByLabel("Email", { exact: true }).fill("ana@exemplu.md");
    await page.getByLabel("Parolă", { exact: true }).fill("parola-mea-123");
    await page.getByLabel("Confirmă parola", { exact: true }).fill("parola-alta-123");
    const submit = page.getByRole("button", { name: "Creează cont", exact: true });
    await expect(submit).toBeDisabled();
    await page.getByRole("checkbox", { name: /Accept Termenii/ }).check();
    await expect(submit).toBeDisabled();
    await page.getByRole("checkbox", { name: /Confirm că sunt părintele/ }).check();
    await submit.click();
    await expect(page.getByRole("alert").filter({ hasText: "Parolele nu coincid." })).toHaveText("Parolele nu coincid.");
    expect(bodies).toHaveLength(0);
    await page.getByLabel("Confirmă parola", { exact: true }).fill("parola-mea-123");
    await Promise.all([page.waitForURL("**/app"), submit.click()]);
    expect(bodies).toEqual([{
      first_name: "Ana", last_name: "Popescu", email: "ana@exemplu.md", password: "parola-mea-123",
      school: "Instituția Publică Liceul Teoretic „M. Eminescu” (MUN.BĂLȚI, BĂLȚI)",
      class_level: "V", privacy_accepted: true, parent_consent: true,
    }]);
  });

  test("instituția poate fi scrisă manual când lista nu se încarcă; erorile API permit reîncercarea", async ({ page }) => {
    let submitted: Record<string, unknown> | undefined;
    await page.route("**/schools-md.json", (route) => route.abort());
    await page.route("**/guguta-api/api/v1/auth/register", (route) => {
      submitted = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({ status: 422, json: { message: "Există deja un cont cu acest email." } });
    });
    await page.goto("/register");
    await page.getByRole("button", { name: "Am înțeles" }).click();
    await page.getByLabel("Prenume", { exact: true }).fill("Ion");
    await page.getByLabel("Nume", { exact: true }).fill("Popescu");
    await page.getByRole("combobox", { name: "Școală / liceu / instituție" }).fill("Liceul Nou, Orhei");
    await page.getByLabel("Clasa", { exact: true }).selectOption("IX");
    await expect(page.getByRole("checkbox", { name: /Confirm că sunt părintele/ })).toHaveCount(0);
    await page.getByLabel("Email", { exact: true }).fill("ion@exemplu.md");
    await page.getByLabel("Parolă", { exact: true }).fill("parola-mea-123");
    await page.getByLabel("Confirmă parola", { exact: true }).fill("parola-mea-123");
    await page.getByRole("checkbox", { name: /Accept Termenii/ }).check();
    const submit = page.getByRole("button", { name: "Creează cont", exact: true });
    await submit.click();
    await expect(page.getByRole("alert").filter({ hasText: "Există deja un cont cu acest email." })).toHaveText("Există deja un cont cu acest email.");
    await expect(submit).toBeEnabled();
    expect(submitted).toMatchObject({ school: "Liceul Nou, Orhei", class_level: "IX", parent_consent: false });
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

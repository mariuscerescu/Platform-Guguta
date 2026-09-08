/**
 * E2E Guguță — fluxuri complete pe UI real (frontend 3001 + API Docker 5056).
 *
 * Acoperire: login → creare carnet → sursă text → upload PDF (procesare worker)
 * → căutare (API) → chat cu citări → notițe → partajare+import (doi utilizatori)
 * → arhivare → ștergere sursă → ștergere carnet.
 *
 * Prerechizițe: frontend pe 3001, API pe 5056 (Docker), worker pornit.
 * Rulare: cd frontend-guguta && npx playwright test
 */
import { expect, test, type Page } from "@playwright/test";

const UNIQUE = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const NB_TITLE = `E2E Carnet ${UNIQUE}`;

let notebookUrl = "";

async function login(page: Page, name: string) {
  await page.goto("/login");
  await page.getByLabel("Numele tău").fill(name);
  const [resp] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().includes("/auth/dev-login"),
      { timeout: 20_000 },
    ),
    page.getByRole("button", { name: "Intră în Guguță" }).click(),
  ]);
  if (!resp.ok()) {
    throw new Error(`dev-login a eșuat: ${resp.status()} ${resp.url()}`);
  }
  await page.waitForURL("**/app");
  // session must actually work before the test proceeds — the homepage
  // renders the "Carnetele mele" heading even when NOT authenticated
  await page.waitForFunction(
    async () => {
      const r = await fetch("/guguta-api/api/v1/auth/me", {
        credentials: "same-origin",
      });
      return r.ok;
    },
    undefined,
    { timeout: 20_000 },
  );
}

async function waitForSourceReady(page: Page, title: string) {
  const card = page.locator(".nb-card, .card", { hasText: title }).first();
  await expect(card).toBeVisible();
  await expect(
    card.locator(".badge.ready, .badge", { hasText: "Gata" }).first(),
  ).toBeVisible({ timeout: 60_000 });
}

test.describe.serial("Fluxuri Guguță E2E", () => {
  test("P01 · login cu cont sintetic", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
  });

  test("P02 · creare carnet și navigare în carnet", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.getByRole("button", { name: "+ Carnet nou" }).click();
    await page.waitForURL(/\/notebook\/[0-9a-f-]+$/);
    notebookUrl = page.url();
    await expect(page.getByRole("tab", { name: "Materiale" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Conversație" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Notițe" })).toBeVisible();
  });

  test("P03 · adăugare sursă text → status Gata", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    const statuses: string[] = [];
    page.on("response", (r) => {
      if (r.url().includes("/api/"))
        statuses.push(
          `${r.status()} ${r.request().method()} ${r.url().split("/api/")[1]}`,
        );
    });
    page.on("request", (r) => {
      if (r.url().includes("/api/") && r.method() === "GET" && !r.url().includes("catalog")) {
        const ck = r.headers()["cookie"] ?? "(none)";
        statuses.push(
          `${r.method()} ${r.url().split("/api/")[1]} :: cookie=${ck.slice(0, 60)}`,
        );
      }
    });
    const title = `Text sursă ${UNIQUE}`;
    try {
      await page.goto(notebookUrl);
      await expect(
        page.getByRole("heading", { name: "Adaugă material (text)" }),
      ).toBeVisible(); // loaded state — form is stable
      await page.locator("#src-title").fill(title);
      await page
        .locator("#src-text")
        .fill(
          "Fotosinteza transforma lumina solara in energie chimica. " +
            "Plantele produc oxigen in timpul fotosintezei.",
        );
      await page.getByRole("button", { name: "Adaugă materialul" }).click();
      try {
        await waitForSourceReady(page, title);
      } catch (err) {
        console.log(
          "P03 page text (paie):",
          (await page.locator("body").innerText()).slice(0, 1200),
        );
        throw err;
      }
    } catch (err) {
      console.log("P03 API responses:\n" + statuses.join("\n"));
      console.log(
        "P03 error-text:",
        await page
          .locator(".error-text")
          .textContent()
          .catch(() => "-"),
      );
      throw err;
    }
  });

  test("P04 · upload fișier PDF → worker procesează → Gata", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    await page.locator('input[type="file"]').setInputFiles({
      name: "proba-e2e.pdf",
      mimeType: "application/pdf",
      buffer: require("fs").readFileSync(
        require("path").join(__dirname, "fixtures", "proba-e2e.pdf"),
      ),
    });
    await waitForSourceReady(page, "proba-e2e.pdf");
  });

  test("P05 · căutare în carnet (API prin proxy-ul frontend)", async ({
    request,
  }) => {
    const nbId = notebookUrl.split("/").pop()!;
    // reuse the browser session cookie? request fixture is isolated — login via API
    const login = await request.post("/guguta-api/api/v1/auth/dev-login", {
      data: { display_name: `E2E User ${UNIQUE}` },
      headers: { Origin: "http://localhost:3001" },
    });
    expect(login.ok()).toBeTruthy();
    const cookie = login.headers()["set-cookie"]!.split(";")[0];
    const csrf = login.headers()["x-guguta-csrf"] ?? "";
    const res = await request.post(
      `/guguta-api/api/v1/notebooks/${nbId}/search`,
      {
        data: { query: "fotosinteza", mode: "text" },
        headers: { Cookie: cookie, "X-Guguta-CSRF": csrf },
      },
    );
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body.results ?? body)).toBeTruthy();
    const text = JSON.stringify(body);
    expect(text).toContain("otosinteza"); // diacritics may vary
  });

  test("P06 · chat: întrebare → răspuns cu citare", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    await page.getByRole("tab", { name: "Conversație" }).click();
    await page.getByRole("button", { name: "Conversație nouă" }).click();
    await page.locator("#draft").fill("Ce este fotosinteza?");
    await page.getByRole("button", { name: "Trimite" }).click();
    const assistant = page.locator(".msg-assistant, .assistant, li", {
      hasText: "Pe baza materialelor selectate",
    });
    await expect(assistant.first()).toBeVisible({ timeout: 30_000 });
  });

  test("P07 · notițe: creare și ștergere", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    await page.getByRole("tab", { name: "Notițe" }).click();
    const title = `Notiță ${UNIQUE}`;
    await page.locator("#note-title").fill(title);
    await page
      .locator("#note-content")
      .fill("Rezumat: fotosinteza = lumina -> energie chimica.");
    await page.getByRole("button", { name: "Salvează notița" }).click();
    await expect(page.getByText(title).first()).toBeVisible();
    const noteCard = page.locator(".card", { hasText: title }).first();
    await noteCard.getByRole("button", { name: "Șterge notița" }).click();
    await expect(page.locator(".card", { hasText: title })).toHaveCount(0);
  });

  test("P08 · partajare: creează link (dialog cu link+cod)", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    let shareText = "";
    page.once("dialog", (d) => {
      shareText = d.message();
      void d.dismiss();
    });
    await page.getByRole("button", { name: "Partajează" }).click();
    await expect
      .poll(() => shareText, { timeout: 15_000 })
      .toContain("/import#token=");
  });

  test("P09 · import cu al doilea utilizator (link → preview → carnet nou)", async ({
    browser,
  }) => {
    // obține un token nou prin API cu primul utilizator
    const nbId = notebookUrl.split("/").pop()!;
    const ctx1 = await browser.newContext();
    const p1 = await ctx1.newPage();
    await login(p1, `E2E User ${UNIQUE}`);
    let token = "";
    p1.once("dialog", (d) => {
      const m = d.message().match(/#token=([A-Za-z0-9_\-]+)/);
      if (m) token = m[1];
      void d.dismiss();
    });
    await p1.goto(notebookUrl);
    await p1.getByRole("button", { name: "Partajează" }).click();
    await expect.poll(() => token, { timeout: 15_000 }).not.toBe("");
    await ctx1.close();

    // al doilea utilizator importă prin pagina /import
    const ctx2 = await browser.newContext();
    const p2 = await ctx2.newPage();
    await login(p2, `E2E Importer ${UNIQUE}`);
    await p2.goto("/import");
    await p2.locator("#token").fill(`http://localhost:3001/import#token=${token}`);
    await p2.getByRole("button", { name: "Verifică" }).click();
    await p2.getByRole("button", { name: "Importă în carnetele mele" }).click();
    await expect(p2.getByText("Import reușit!")).toBeVisible({ timeout: 30_000 });
    await ctx2.close();
  });

  test("P10 · arhivare și restaurare carnet", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    await page.getByRole("button", { name: "Arhivează" }).click();
    await expect(page.getByRole("button", { name: "Dezarhivează" })).toBeVisible();
    await page.getByRole("button", { name: "Dezarhivează" }).click();
    await expect(page.getByRole("button", { name: "Arhivează" })).toBeVisible();
  });

  test("P11 · ștergere sursă (fișier)", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    const card = page
      .locator(".card", { hasText: "proba-e2e.pdf" })
      .first();
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Elimină" }).click();
    await expect(page.locator(".card", { hasText: "proba-e2e.pdf" })).toHaveCount(
      0,
    );
  });

  test("P12 · ștergere carnet → redirect la homepage", async ({ page }) => {
    await login(page, `E2E User ${UNIQUE}`);
    await page.goto(notebookUrl);
    page.once("dialog", (d) => void d.accept());
    await page.getByRole("button", { name: "Șterge" }).click();
    await page.waitForURL("**/app");
    await expect(page.getByRole("heading", { name: "Carnetele mele" })).toBeVisible();
  });

  test("P13 · catalogul școlar: chip și căutare", async ({ page }) => {
    await login(page, `E2E Catalog ${UNIQUE}`);
    await page.getByRole("button", { name: "Carnete școlare" }).click();
    await expect(
      page.getByRole("heading", { name: "Carnete școlare" }),
    ).toBeVisible();
    // căutarea filtrează pe titlu (catalog gol → mesaj de gol)
    await page
      .getByPlaceholder("Caută carnet după titlu")
      .fill("geografie-inexistentă-e2e");
    await expect(
      page.getByText("Catalogul școlar nu are încă carnete publicate.").or(
        page.getByText("nu are încă"),
      ),
    ).toBeVisible();
  });
});

# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: flows.spec.ts >> Fluxuri Guguță E2E >> P01 · login cu cont sintetic
- Location: e2e\flows.spec.ts:55:7

# Error details

```
Error: dev-login a eșuat: 500 http://localhost:3001/guguta-api/api/v1/auth/dev-login
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - banner [ref=e2]:
    - generic [ref=e3]: Guguță
  - main [ref=e4]:
    - heading "Autentificare" [level=1] [ref=e5]
    - paragraph [ref=e6]: Autentificare eșuată.
    - paragraph [ref=e7]: "Mod de dezvoltare: cont sintetic local. În producție autentificarea se face prin furnizorul de identitate al școlii (OIDC)."
    - generic [ref=e8]:
      - text: Numele tău
      - textbox "Numele tău" [ref=e9]:
        - /placeholder: ex. Maria Popescu
        - text: E2E User mtrat546spj2
      - button "Intră în Guguță" [ref=e10] [cursor=pointer]
  - alert [ref=e11]
```

# Test source

```ts
  1   | /**
  2   |  * E2E Guguță — fluxuri complete pe UI real (frontend 3001 + API Docker 5056).
  3   |  *
  4   |  * Acoperire: login → creare carnet → sursă text → upload PDF (procesare worker)
  5   |  * → căutare (API) → chat cu citări → notițe → partajare+import (doi utilizatori)
  6   |  * → arhivare → ștergere sursă → ștergere carnet.
  7   |  *
  8   |  * Prerechizițe: frontend pe 3001, API pe 5056 (Docker), worker pornit.
  9   |  * Rulare: cd frontend-guguta && npx playwright test
  10  |  */
  11  | import { expect, test, type Page } from "@playwright/test";
  12  | 
  13  | const UNIQUE = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  14  | const NB_TITLE = `E2E Carnet ${UNIQUE}`;
  15  | 
  16  | let notebookUrl = "";
  17  | 
  18  | async function login(page: Page, name: string) {
  19  |   await page.goto("/login");
  20  |   await page.getByLabel("Numele tău").fill(name);
  21  |   const [resp] = await Promise.all([
  22  |     page.waitForResponse(
  23  |       (r) => r.url().includes("/auth/dev-login"),
  24  |       { timeout: 20_000 },
  25  |     ),
  26  |     page.getByRole("button", { name: "Intră în Guguță" }).click(),
  27  |   ]);
  28  |   if (!resp.ok()) {
> 29  |     throw new Error(`dev-login a eșuat: ${resp.status()} ${resp.url()}`);
      |           ^ Error: dev-login a eșuat: 500 http://localhost:3001/guguta-api/api/v1/auth/dev-login
  30  |   }
  31  |   await page.waitForURL("**/");
  32  |   // session must actually work before the test proceeds — the homepage
  33  |   // renders the "Carnetele mele" heading even when NOT authenticated
  34  |   await page.waitForFunction(
  35  |     async () => {
  36  |       const r = await fetch("/guguta-api/api/v1/auth/me", {
  37  |         credentials: "same-origin",
  38  |       });
  39  |       return r.ok;
  40  |     },
  41  |     undefined,
  42  |     { timeout: 20_000 },
  43  |   );
  44  | }
  45  | 
  46  | async function waitForSourceReady(page: Page, title: string) {
  47  |   const card = page.locator(".nb-card, .card", { hasText: title }).first();
  48  |   await expect(card).toBeVisible();
  49  |   await expect(
  50  |     card.locator(".badge.ready, .badge", { hasText: "Gata" }).first(),
  51  |   ).toBeVisible({ timeout: 60_000 });
  52  | }
  53  | 
  54  | test.describe.serial("Fluxuri Guguță E2E", () => {
  55  |   test("P01 · login cu cont sintetic", async ({ page }) => {
  56  |     await login(page, `E2E User ${UNIQUE}`);
  57  |   });
  58  | 
  59  |   test("P02 · creare carnet și navigare în carnet", async ({ page }) => {
  60  |     await login(page, `E2E User ${UNIQUE}`);
  61  |     await page.getByRole("button", { name: "+ Carnet nou" }).click();
  62  |     await page.waitForURL(/\/notebook\/[0-9a-f-]+$/);
  63  |     notebookUrl = page.url();
  64  |     await expect(page.getByRole("tab", { name: "Materiale" })).toBeVisible();
  65  |     await expect(page.getByRole("tab", { name: "Conversație" })).toBeVisible();
  66  |     await expect(page.getByRole("tab", { name: "Notițe" })).toBeVisible();
  67  |   });
  68  | 
  69  |   test("P03 · adăugare sursă text → status Gata", async ({ page }) => {
  70  |     await login(page, `E2E User ${UNIQUE}`);
  71  |     const statuses: string[] = [];
  72  |     page.on("response", (r) => {
  73  |       if (r.url().includes("/api/"))
  74  |         statuses.push(
  75  |           `${r.status()} ${r.request().method()} ${r.url().split("/api/")[1]}`,
  76  |         );
  77  |     });
  78  |     page.on("request", (r) => {
  79  |       if (r.url().includes("/api/") && r.method() === "GET" && !r.url().includes("catalog")) {
  80  |         const ck = r.headers()["cookie"] ?? "(none)";
  81  |         statuses.push(
  82  |           `${r.method()} ${r.url().split("/api/")[1]} :: cookie=${ck.slice(0, 60)}`,
  83  |         );
  84  |       }
  85  |     });
  86  |     const title = `Text sursă ${UNIQUE}`;
  87  |     try {
  88  |       await page.goto(notebookUrl);
  89  |       await expect(
  90  |         page.getByRole("heading", { name: "Adaugă material (text)" }),
  91  |       ).toBeVisible(); // loaded state — form is stable
  92  |       await page.locator("#src-title").fill(title);
  93  |       await page
  94  |         .locator("#src-text")
  95  |         .fill(
  96  |           "Fotosinteza transforma lumina solara in energie chimica. " +
  97  |             "Plantele produc oxigen in timpul fotosintezei.",
  98  |         );
  99  |       await page.getByRole("button", { name: "Adaugă materialul" }).click();
  100 |       try {
  101 |         await waitForSourceReady(page, title);
  102 |       } catch (err) {
  103 |         console.log(
  104 |           "P03 page text (paie):",
  105 |           (await page.locator("body").innerText()).slice(0, 1200),
  106 |         );
  107 |         throw err;
  108 |       }
  109 |     } catch (err) {
  110 |       console.log("P03 API responses:\n" + statuses.join("\n"));
  111 |       console.log(
  112 |         "P03 error-text:",
  113 |         await page
  114 |           .locator(".error-text")
  115 |           .textContent()
  116 |           .catch(() => "-"),
  117 |       );
  118 |       throw err;
  119 |     }
  120 |   });
  121 | 
  122 |   test("P04 · upload fișier PDF → worker procesează → Gata", async ({ page }) => {
  123 |     await login(page, `E2E User ${UNIQUE}`);
  124 |     await page.goto(notebookUrl);
  125 |     await page.locator('input[type="file"]').setInputFiles({
  126 |       name: "proba-e2e.pdf",
  127 |       mimeType: "application/pdf",
  128 |       buffer: require("fs").readFileSync(
  129 |         require("path").join(__dirname, "fixtures", "proba-e2e.pdf"),
```
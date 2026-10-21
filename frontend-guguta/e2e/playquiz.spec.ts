/**
 * E2E Guguță — „Deschide în PlayQuiz” (ADR-023).
 *
 * Login și carnet reale (frontend 3001 + API 5056); quizul și endpointurile
 * PlayQuiz sunt simulate cu `page.route`, ca fluxul să nu depindă de worker,
 * de modelul de chat sau de un server PlayQuiz real.
 *
 * Rulare: cd frontend-guguta && npx playwright test e2e/playquiz.spec.ts
 */
import { expect, test, type Page, type Route } from "@playwright/test";

const UNIQUE = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
const QUIZ_ID = "11111111-1111-4111-8111-111111111111";
const QUESTION_ID = "22222222-2222-4222-8222-222222222222";
const ATTEMPT_ID = "33333333-3333-4333-8333-333333333333";

async function login(page: Page, name: string) {
  await page.goto("/login");
  await page.getByLabel("Numele tău").fill(name);
  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/auth/dev-login"), { timeout: 20_000 }),
    page.getByRole("button", { name: "Intră în Guguță" }).click(),
  ]);
  await page.waitForURL("**/app");
  await page.waitForFunction(
    async () => (await fetch("/guguta-api/api/v1/auth/me", { credentials: "same-origin" })).ok,
    undefined,
    { timeout: 20_000 },
  );
}

async function createNotebook(page: Page): Promise<string> {
  await page.getByRole("button", { name: "Carnet nou" }).click();
  await page.getByRole("button", { name: "Creează carnet" }).click();
  await page.waitForURL(/\/notebook\/[0-9a-f-]+$/);
  return page.url();
}

const quizSummary = {
  id: QUIZ_ID,
  quantity: "fewer",
  difficulty: "easy",
  question_types: ["multiple_choice"],
  selected_source_ids: [],
  status: "ready",
  title: "Adunarea până la 10",
  question_count: 1,
};

const quizDetail = {
  ...quizSummary,
  questions: [
    {
      id: QUESTION_ID,
      position: 0,
      question_type: "multiple_choice",
      prompt: "Cât fac 3 + 4?",
      hint: "Numără pe degete.",
      concepts: ["adunare"],
      options: [{ id: "a", text: "7" }, { id: "b", text: "6" }],
      version: 1,
    },
  ],
  active_attempt: null,
};

const attempt = { id: ATTEMPT_ID, current_index: 0, question_order: [QUESTION_ID], answers: {}, completed_at: null };

/** Quiz gata, simulat, ca dialogul de quiz să se deschidă fără generare. */
async function mockQuiz(page: Page) {
  await page.route("**/guguta-api/api/v1/notebooks/*/quizzes", (route) =>
    route.request().method() === "GET" ? route.fulfill({ json: [quizSummary] }) : route.continue(),
  );
  await page.route(`**/guguta-api/api/v1/notebooks/*/quizzes/${QUIZ_ID}`, (route) => route.fulfill({ json: quizDetail }));
  await page.route(`**/guguta-api/api/v1/notebooks/*/quizzes/${QUIZ_ID}/attempts`, (route) =>
    route.fulfill({ status: 201, json: attempt }),
  );
}

/** /auth/me real, cu capabilitatea `playquiz` suprascrisă. */
async function mockCapability(page: Page, enabled: boolean) {
  await page.route("**/guguta-api/api/v1/auth/me", async (route: Route) => {
    const response = await route.fetch();
    const body = (await response.json()) as Record<string, unknown>;
    await route.fulfill({ response, json: { ...body, capabilities: { playquiz: enabled } } });
  });
}

test.describe("Deschide în PlayQuiz", () => {
  test("cu capabilitatea activă: acord o singură dată, apoi fereastră nouă cu URL-ul de handoff", async ({ page }) => {
    await login(page, `E2E PlayQuiz ${UNIQUE}`);
    const notebookUrl = await createNotebook(page);

    let consentGiven = false;
    const exportBodies: Array<{ consent?: boolean }> = [];
    await mockCapability(page, true);
    await mockQuiz(page);
    await page.route(`**/guguta-api/api/v1/notebooks/*/quizzes/${QUIZ_ID}/playquiz`, async (route) => {
      if (route.request().method() === "GET") {
        return route.fulfill({
          json: { enabled: true, consent_given: consentGiven, exportable: true, reason: null, exported: false, play_url: null, exported_at: null },
        });
      }
      const body = route.request().postDataJSON() as { consent?: boolean };
      exportBodies.push(body);
      if (!consentGiven && !body.consent) {
        return route.fulfill({ status: 409, json: { code: "consent_required", message: "Este nevoie de acordul tău." } });
      }
      consentGiven = true;
      // URL pe aceeași origine, ca testul să nu depindă de rețea; pagina poate fi 404.
      return route.fulfill({ json: { url: "/handoff-simulat?token=abc", quiz_id: "99", play_url: "/quiz/custom/99", created: true, updated: false } });
    });

    await page.goto(notebookUrl);
    await page.getByRole("button", { name: /Deschide Adunarea până la 10/ }).first().click();
    await expect(page.getByRole("dialog").getByRole("heading", { name: "Adunarea până la 10" })).toBeVisible();

    const openButton = page.getByTestId("open-in-playquiz");
    await expect(openButton).toBeEnabled();
    await openButton.click();
    await expect(page.getByRole("heading", { name: "Deschide în PlayQuiz" })).toBeVisible();
    expect(exportBodies).toHaveLength(0); // nimic nu pleacă înainte de acord

    const [popup] = await Promise.all([
      page.waitForEvent("popup"),
      page.getByTestId("playquiz-consent-accept").click(),
    ]);
    await popup.waitForURL(/handoff-simulat\?token=abc/);
    expect(exportBodies).toEqual([{ consent: true }]);
    await expect(page.getByRole("heading", { name: "Deschide în PlayQuiz" })).toBeHidden();

    // Al doilea click: fără dialog de acord.
    const [second] = await Promise.all([page.waitForEvent("popup"), openButton.click()]);
    await second.waitForURL(/handoff-simulat\?token=abc/);
    expect(exportBodies).toEqual([{ consent: true }, { consent: false }]);
  });

  test("fără capabilitate butonul lipsește; quizul rămâne jucabil în Guguță", async ({ page }) => {
    await login(page, `E2E fără PlayQuiz ${UNIQUE}`);
    const notebookUrl = await createNotebook(page);
    await mockCapability(page, false);
    await mockQuiz(page);
    let statusCalls = 0;
    await page.route(`**/guguta-api/api/v1/notebooks/*/quizzes/${QUIZ_ID}/playquiz`, (route) => {
      statusCalls += 1;
      return route.fulfill({ status: 409, json: { code: "playquiz_disabled", message: "inactiv" } });
    });

    await page.goto(notebookUrl);
    await page.getByRole("button", { name: /Deschide Adunarea până la 10/ }).first().click();
    await expect(page.getByRole("dialog").getByText("Cât fac 3 + 4?")).toBeVisible();
    await expect(page.getByTestId("open-in-playquiz")).toHaveCount(0);
    expect(statusCalls).toBe(0);
  });
});

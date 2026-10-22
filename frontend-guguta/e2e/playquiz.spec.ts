/** PlayQuiz export UI with synthetic API responses; no accounts or external exports. */
import { expect, test, type Page } from "@playwright/test";

const BASE_PATH = process.env.GUGUTA_E2E_BASE_PATH ?? "";
const NOTEBOOK_ID = "11111111-1111-4111-8111-111111111111";
const QUIZ_ID = "22222222-2222-4222-8222-222222222222";
const QUESTION_ID = "33333333-3333-4333-8333-333333333333";
const ATTEMPT_ID = "44444444-4444-4444-8444-444444444444";
const title = "Adunarea până la 10";

type Setup = { enabled?: boolean; kind?: string; outage?: boolean; conflict?: boolean };
async function setup(page: Page, { enabled = true, kind = "multiple_choice", outage = false, conflict = false }: Setup = {}) {
  let consentGiven = false;
  const bodies: Array<{ consent?: boolean }> = [];
  const summary = { id: QUIZ_ID, status: "ready", title, quantity: "fewer", difficulty: "easy",
    question_types: [kind], selected_source_ids: [], question_count: 1 };
  const detail = { ...summary, active_attempt: null, questions: [{ id: QUESTION_ID, position: 0,
    question_type: kind === "mixed" ? "multiple_choice" : kind, prompt: "Cât fac 3 + 4?", hint: "Numără.", concepts: [], version: 1,
    options: kind === "short_answer" ? [] : [{ id: "a", text: "7" }, { id: "b", text: "6" }], accepted_answers: [] }] };
  if (kind === "mixed") detail.questions.push({ ...detail.questions[0], id: "66666666-6666-4666-8666-666666666666", question_type: "short_answer", options: [] });
  await page.addInitScript(() => {
    localStorage.setItem("guguta_csrf", "synthetic-csrf");
    localStorage.setItem("guguta.cookie-notice.v1", "seen");
  });
  await page.route("**/guguta-api/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.split("/api/v1")[1];
    if (path === "/auth/me") return route.fulfill({ json: { id: "synthetic-user", display_name: "Elev fictiv", roles: ["user"], capabilities: { playquiz: enabled } } });
    if (path === "/auth/csrf") return route.fulfill({ json: { actor_id: "synthetic-user", csrf: "synthetic-csrf" } });
    if (path === "/voice/providers") return route.fulfill({ json: { providers: [] } });
    if (path === `/notebooks/${NOTEBOOK_ID}`) return route.fulfill({ json: { id: NOTEBOOK_ID, title: "Carnet fictiv", status: "active", origin: "personal", context_revision: 1 } });
    if (path.endsWith("/playquiz")) {
      if (route.request().method() === "GET") return route.fulfill({ json: { enabled, consent_given: consentGiven, exportable: true, exported: conflict && consentGiven, play_url: conflict && consentGiven ? "https://play-quiz.example/partners/play/synthetic" : null } });
      const body = route.request().postDataJSON() as { consent?: boolean };
      bodies.push(body);
      expect(route.request().headers()["x-guguta-csrf"]).toBe("synthetic-csrf");
      if (!enabled) return route.fulfill({ status: 409, json: { code: "playquiz_disabled", message: "Conexiunea cu PlayQuiz nu este încă disponibilă. Poți continua quizul aici." } });
      if (conflict) {
        consentGiven = true;
        return route.fulfill({ status: 409, json: { code: "playquiz_account_conflict", message: "Există deja un cont PlayQuiz cu acest e-mail." } });
      }
      if (outage) return route.fulfill({ status: 503, json: { code: "playquiz_unavailable", message: "PlayQuiz nu este disponibil acum." } });
      consentGiven = true;
      return route.fulfill({ json: { url: `${BASE_PATH}/handoff-simulat?token=synthetic`, quiz_id: "99", created: true } });
    }
    if (path === `/notebooks/${NOTEBOOK_ID}/quizzes`) return route.fulfill({ json: [summary] });
    if (path.endsWith(`/quizzes/${QUIZ_ID}`)) return route.fulfill({ json: detail });
    if (path.endsWith(`/quizzes/${QUIZ_ID}/attempts`)) return route.fulfill({ json: { id: ATTEMPT_ID, current_index: 0, question_order: [QUESTION_ID], answers: {}, completed_at: null } });
    if (path.endsWith("/sessions")) return route.fulfill({ json: [{ id: "55555555-5555-4555-8555-555555555555", created_revision: 1 }] });
    return route.fulfill({ json: [] });
  });
  const statusReady = ["multiple_choice", "multiple_select"].includes(kind)
    ? page.waitForResponse(response => response.url().endsWith(`/quizzes/${QUIZ_ID}/playquiz`) && response.request().method() === "GET")
    : null;
  await page.goto(`${BASE_PATH}/notebook/${NOTEBOOK_ID}`);
  await page.locator("button.flashcard-deck-open").filter({ hasText: title }).click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: title })).toBeVisible();
  if (statusReady) await (await statusReady).finished();
  await expect(page).toHaveURL(new RegExp(`/notebook/${NOTEBOOK_ID}$`));
  return bodies;
}

test("grid quiz stays native; consent then POST opens handoff in a new window", async ({ page }) => {
  const bodies = await setup(page);
  const button = page.getByTestId("open-in-playquiz");
  await expect(button).toBeVisible();
  await button.click();
  await expect(page.getByRole("heading", { name: "Deschide în PlayQuiz" })).toBeVisible();
  expect(bodies).toEqual([]);
  const [popup] = await Promise.all([page.waitForEvent("popup"), page.getByTestId("playquiz-consent-accept").click()]);
  await popup.waitForURL(/handoff-simulat\?token=synthetic/);
  expect(bodies).toEqual([{ consent: true }]);
  await expect(page.getByRole("heading", { name: "Deschide în PlayQuiz" })).toBeHidden();
  const [again] = await Promise.all([page.waitForEvent("popup"), button.click()]);
  await again.waitForURL(/handoff-simulat\?token=synthetic/);
  expect(bodies).toEqual([{ consent: true }, { consent: false }]);
});

test("without partner configuration the grid button remains visible and reports the POST error", async ({ page }) => {
  const bodies = await setup(page, { enabled: false });
  const button = page.getByTestId("open-in-playquiz");
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByRole("alert").filter({ hasText: "Conexiunea cu PlayQuiz" })).toBeVisible();
  expect(bodies).toEqual([{ consent: false }]);
  await expect(page.getByRole("dialog").getByText("Cât fac 3 + 4?")).toBeVisible();
  await expect(button).toBeEnabled();
});

test("multiple-select quizzes also show the export button", async ({ page }) => {
  await setup(page, { kind: "multiple_select" });
  await expect(page.getByTestId("open-in-playquiz")).toBeVisible();
});

for (const kind of ["short_answer", "mixed"]) {
  test(`${kind} quizzes stay native without an export button`, async ({ page }) => {
    await setup(page, { kind });
    await expect(page.getByTestId("open-in-playquiz")).toHaveCount(0);
  });
}

test("partner failure keeps the native quiz available and allows retry", async ({ page }) => {
  const bodies = await setup(page, { outage: true });
  await page.getByTestId("open-in-playquiz").click();
  await page.getByTestId("playquiz-consent-accept").click();
  await expect(page.getByRole("alert").filter({ hasText: "PlayQuiz nu este disponibil" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Deschide în PlayQuiz" })).toBeHidden();
  expect(bodies).toEqual([{ consent: true }]);
  await expect(page.getByTestId("open-in-playquiz")).toBeEnabled();
});


test("existing PlayQuiz email offers the saved quiz link without repeated export", async ({ page }) => {
  const bodies = await setup(page, { conflict: true });
  await page.getByTestId("open-in-playquiz").click();
  await expect(page.getByText("La prima intrare vei alege o parolă", { exact: false })).toBeVisible();
  await page.getByTestId("playquiz-consent-accept").click();
  await expect(page.getByRole("alert").filter({ hasText: "Există deja un cont" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Conectează-te în PlayQuiz și deschide quizul" })).toHaveAttribute("href", "https://play-quiz.example/partners/play/synthetic");
  expect(bodies).toEqual([{ consent: true }]);
});

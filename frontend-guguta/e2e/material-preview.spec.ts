/** Synthetic documents only; all API traffic stays mocked in the browser. */
import { expect, test, type Page } from "@playwright/test";

const BASE = process.env.GUGUTA_E2E_BASE_PATH ?? "";
const NB = "11111111-1111-4111-8111-111111111111";
const SID = "22222222-2222-4222-8222-222222222222";
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII=", "base64");

function samplePdf() {
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"];
  const stream = "BT /F1 24 Tf 60 750 Td (Material demonstrativ) Tj ET";
  objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, i) => { offsets.push(pdf.length); pdf += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map(offset => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  return Buffer.from(`${pdf}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`);
}

async function setup(page: Page, mime: string, body: string | Buffer, status = 200) {
  let previewCalls = 0;
  let patches = 0;
  await page.addInitScript(() => {
    localStorage.setItem("guguta_csrf", "synthetic");
    localStorage.setItem("guguta.cookie-notice.v1", "seen");
  });
  await page.route("**/guguta-api/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.split("/api/v1")[1];
    if (route.request().method() === "PATCH") patches++;
    if (path === "/auth/me") return route.fulfill({ json: { id: "synthetic", display_name: "Elev fictiv", roles: ["user"], capabilities: {} } });
    if (path === "/auth/csrf") return route.fulfill({ json: { csrf: "synthetic", actor_id: "synthetic" } });
    if (path === "/voice/providers") return route.fulfill({ json: { providers: [] } });
    if (path === `/notebooks/${NB}`) return route.fulfill({ json: { id: NB, title: "Carnet demonstrativ", origin: "personal", status: "active", context_revision: 1 } });
    if (path === `/notebooks/${NB}/sources`) return route.fulfill({ json: [{ id: SID, local_name: "Material demonstrativ", original_name: "material", mime_type: mime,
      material_version_id: SID, selected_for_chat: true, status: "ready" }] });
    if (path.endsWith("/preview")) {
      previewCalls++;
      return route.fulfill({ status, contentType: mime.includes("officedocument") ? "text/plain" : mime, body });
    }
    if (path.endsWith("/download")) return route.fulfill({ contentType: mime, body });
    if (path.endsWith("/sessions")) return route.fulfill({ json: [{ id: "session", created_revision: 1 }] });
    return route.fulfill({ json: [] });
  });
  await page.goto(`${BASE}/notebook/${NB}`);
  if (page.viewportSize()!.width < 991) await page.getByRole("button", { name: "Materiale", exact: true }).click();
  const trigger = page.locator("button.src-name", { hasText: "Material demonstrativ" });
  await expect(trigger).toBeVisible();
  expect(previewCalls).toBe(0);
  await trigger.click();
  return { calls: () => previewCalls, patches: () => patches, trigger };
}

test("PDF opens in a large modal, closes with Escape and preserves source selection", async ({ page }) => {
  const state = await setup(page, "application/pdf", samplePdf());
  const dialog = page.getByRole("dialog", { name: "Material demonstrativ" });
  await expect(dialog.locator("iframe")).toHaveAttribute("src", /^blob:.*#view=FitH$/);
  await expect(dialog.getByRole("link", { name: "Descarcă", exact: true })).toHaveAttribute("href", /\/sources\/.*\/download$/);
  const bounds = await dialog.boundingBox();
  expect(bounds!.width).toBeGreaterThan(page.viewportSize()!.width * .9);
  expect(bounds!.height).toBeGreaterThan(page.viewportSize()!.height * .9);
  await page.screenshot({ path: test.info().outputPath("pdf-preview.png") });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(state.trigger).toBeFocused();
  expect(state.patches()).toBe(0);
  await expect(page.locator(".src-sel input")).toBeChecked();
});

test("image preview fits a phone and closes without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page, "image/png", PNG);
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("img", { name: "Material demonstrativ" })).toBeVisible();
  expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBeTruthy();
  await page.screenshot({ path: test.info().outputPath("image-mobile.png") });
  await dialog.getByRole("button", { name: "Mărește" }).click();
  await expect(dialog.getByRole("button", { name: "Potrivește" })).toHaveAttribute("aria-pressed", "true");
  await dialog.getByRole("button", { name: "Închide previzualizarea" }).click();
  await expect(dialog).toHaveCount(0);
});

test("text links are useful without running HTML or loading external images", async ({ page }) => {
  let remoteRequests = 0;
  await page.route("https://example.com/**", route => { remoteRequests++; return route.abort(); });
  await setup(page, "text/plain", '# Lecția\n\nText pentru citit.\n\nhttps://example.com/lectie\n\n![imagine externă](https://example.com/tracker.png)\n\n<script>window.previewUnsafe=true</script>');
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Text pentru citit.")).toBeVisible();
  await expect(dialog.getByRole("link", { name: "https://example.com/lectie" })).toHaveAttribute("rel", "noopener noreferrer");
  expect(await page.evaluate(() => "previewUnsafe" in window)).toBe(false);
  expect(remoteRequests).toBe(0);
  await page.screenshot({ path: test.info().outputPath("text-preview.png") });
});

test("Office text preview labels its limitation; denied files show a retryable error", async ({ page }) => {
  await setup(page, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Lecția din document");
  await expect(page.getByRole("dialog").getByText("Lecția din document")).toBeVisible();
  await expect(page.getByText("Textul documentului. Pentru aspectul original, descarcă fișierul.")).toBeVisible();
  await page.unrouteAll();
  const state = await setup(page, "application/pdf", "Denied", 404);
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("nu mai este disponibil");
  const callsBeforeRetry = state.calls();
  await page.getByRole("button", { name: "Reîncearcă" }).click();
  await expect.poll(state.calls).toBe(callsBeforeRetry + 1);
});

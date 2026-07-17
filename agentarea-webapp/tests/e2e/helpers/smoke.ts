import { expect, type Page } from "@playwright/test";

/**
 * Shared "did this route render without crashing" assertion for the
 * deterministic (no-AI) smoke specs.
 *
 * Waits only for the navigation to commit (first byte), not full
 * DOMContentLoaded: streaming-SSR routes keep the HTML document open, so a naive
 * goto would hang until timeout. `commit` still yields the HTTP status and the
 * landed URL, which is what the smoke asserts. A route that cannot even return
 * its first byte within 25s is reported as a slow/hanging SSR defect.
 */
export async function assertRenders(page: Page, route: string) {
  let response = null;
  try {
    response = await page.goto(route, { waitUntil: "commit", timeout: 25_000 });
  } catch (error) {
    const message = String(error);
    if (message.includes("ERR_ABORTED")) {
      // A client-side redirect aborts the original navigation; benign, we
      // assert on the landed state below.
    } else if (message.includes("Timeout")) {
      throw new Error(
        `${route} did not return its first byte within 25s - slow or hanging server-side render (e.g. a blocking SSR data fetch)`
      );
    } else {
      throw error;
    }
  }

  // Not bounced back to the login flow.
  expect(page.url(), `${route} should not redirect to login`).not.toMatch(
    /\/auth\/login/
  );

  // HTTP layer did not return a hard error for the document.
  if (response) {
    expect(response.status(), `${route} HTTP status`).toBeLessThan(400);
  }

  // Give the shell a brief, non-fatal window to paint, then assert the (main)
  // error boundary did not trip. Best-effort so streaming pages that never reach
  // DOMContentLoaded still get checked on whatever rendered.
  await page
    .waitForLoadState("domcontentloaded", { timeout: 8_000 })
    .catch(() => undefined);
  await expect(
    page.getByText("Something went wrong", { exact: false }),
    `${route} should not show the error boundary`
  ).toHaveCount(0);
}

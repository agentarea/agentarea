import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import {
  authedRequest,
  createKratosUser,
  deleteKratosUser,
  installBrowserSession,
  type AuthedUser,
} from "./helpers/real-stack";
import { gotoCommitted, runRealStack } from "./helpers/scenarios";

async function createFolder(page: Page, name: string) {
  const dialog = page.getByRole("dialog");
  // A click that lands before hydration opens nothing; retry until it does.
  await expect(async () => {
    if (!(await dialog.isVisible()))
      await page.getByRole("button", { name: "New folder", exact: true }).click({ timeout: 2_000 });
    await expect(dialog).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 30_000 });
  await dialog.getByLabel("Folder name", { exact: true }).fill(name);
  await dialog
    .getByRole("button", { name: "Create folder", exact: true })
    .click();
  // Creation is a server action: ~1s alone in dev, over 5s under suite load.
  await expect(dialog).toBeHidden({ timeout: 20_000 });
}

// Folder changes go through router.replace, a server round trip that takes
// well over the default 5s under suite load.
const FOLDER_NAV_TIMEOUT = 15_000;

function contentRow(page: Page, name: string) {
  return page.getByRole("row").filter({
    has: page.getByText(name, { exact: true }),
  });
}

test.describe("Workspace folder view", () => {
  test.skip(!runRealStack, "Set PLAYWRIGHT_REAL_STACK=1");

  let user: AuthedUser;

  test.beforeAll(async () => {
    user = await createKratosUser("workspace-folder-view");
  });

  test.afterAll(async () => {
    if (user) await deleteKratosUser(user.identityId);
  });

  test("creates persistent nested folders, uploads into the selected folder, searches and previews files on desktop and mobile", async ({
    context,
    page,
    request,
  }, testInfo) => {
    test.setTimeout(180_000);
    await installBrowserSession(context, user);
    await gotoCommitted(page, "/files");

    const folderTree = page.getByRole("complementary", {
      name: "File tree",
      exact: true,
    });
    // The open folder is the selected tab of the file manager.
    const openFolder = (name: string) =>
      page
        .getByRole("tablist", { name: "Open files", exact: true })
        .getByRole("tab", { name, exact: true, selected: true });
    await expect(folderTree).toBeVisible();
    await expect(
      folderTree.getByText("All files", { exact: true })
    ).toBeVisible();
    await expect(page.getByPlaceholder("Search this folder")).toBeVisible();

    await createFolder(page, "Materials");
    await contentRow(page, "Materials")
      .getByText("Materials", { exact: true })
      .click();
    await expect(openFolder("Materials")).toBeVisible({ timeout: FOLDER_NAV_TIMEOUT });

    await createFolder(page, "Drafts");
    await expect(contentRow(page, "Drafts")).toBeVisible();

    // Re-fetch the root from the server before navigating back to the empty
    // child. This proves folders survive beyond the creating page's state.
    await page.reload({ waitUntil: "domcontentloaded" });
    // Right after the reload a tree click can land before hydration and be
    // dropped; retry until the root listing shows.
    await expect(async () => {
      await folderTree.getByText("All files", { exact: true }).click({ timeout: 2_000 });
      await expect(contentRow(page, "Materials")).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await contentRow(page, "Materials")
      .getByText("Materials", { exact: true })
      .click();
    await expect(contentRow(page, "Drafts")).toBeVisible({ timeout: FOLDER_NAV_TIMEOUT });

    // The tree and the contents table must drive the same current folder.
    await folderTree.getByText("All files", { exact: true }).click();
    await expect(contentRow(page, "Materials")).toBeVisible({ timeout: FOLDER_NAV_TIMEOUT });
    await folderTree.getByText("Materials", { exact: true }).click();
    await contentRow(page, "Drafts")
      .getByText("Drafts", { exact: true })
      .click();
    await expect(openFolder("Drafts")).toBeVisible({ timeout: FOLDER_NAV_TIMEOUT });

    const filename =
      "Quarterly-research-notes-with-a-long-descriptive-filename.txt";
    const contents = "These notes belong inside Materials/Drafts.\n";
    const chooserPromise = page.waitForEvent("filechooser");
    await page
      .getByRole("button", { name: "Upload files", exact: true })
      .click();
    const chooser = await chooserPromise;
    await chooser.setFiles({
      name: filename,
      mimeType: "text/plain",
      buffer: Buffer.from(contents),
    });
    await expect(contentRow(page, filename)).toBeVisible({ timeout: 30_000 });

    const uploadDirectory = testInfo.outputPath("folder-upload", "References");
    await mkdir(path.join(uploadDirectory, "sources"), { recursive: true });
    await writeFile(
      path.join(uploadDirectory, "sources", "reading-list.txt"),
      "Read these sources.\n"
    );
    await page
      .getByRole("button", { name: "Upload options", exact: true })
      .click();
    const folderChooserPromise = page.waitForEvent("filechooser");
    await page
      .getByRole("menuitem", { name: "Upload folder", exact: true })
      .click();
    await (await folderChooserPromise).setFiles(uploadDirectory);
    await expect(contentRow(page, "References")).toBeVisible({
      timeout: 30_000,
    });

    const listing = await authedRequest(request, user, "get", "/v1/files");
    expect(listing.ok()).toBeTruthy();
    const payload = await listing.json();
    expect(payload.directories).toEqual(
      expect.arrayContaining(["Materials/", "Materials/Drafts/"])
    );
    expect(payload.files).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ path: `Materials/Drafts/${filename}` }),
        expect.objectContaining({
          path: "Materials/Drafts/References/sources/reading-list.txt",
        }),
      ])
    );
    expect(payload.files).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ path: filename })])
    );

    const search = page.getByPlaceholder("Search this folder");
    await search.fill("not-present-anywhere");
    await expect(contentRow(page, filename)).toHaveCount(0);
    await search.fill("QUARTERLY");
    await expect(contentRow(page, filename)).toBeVisible();
    await search.clear();

    await contentRow(page, filename)
      .getByText(filename, { exact: true })
      .click();
    // A file opens as a tab of the "Open files" strip, named after the file.
    const preview = page.getByRole("tabpanel", { name: filename, exact: true });
    await expect(preview).toBeVisible({ timeout: 15_000 });
    await expect(
      preview.getByText(contents.trim(), { exact: true })
    ).toBeVisible({
      timeout: 20_000,
    });
    await page.getByRole("button", { name: `Close ${filename}`, exact: true }).click();
    await expect(preview).toBeHidden();

    await page.setViewportSize({ width: 390, height: 844 });
    await expect(
      page.getByRole("button", { name: "New folder", exact: true })
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Upload files", exact: true })
    ).toBeVisible();
    await expect(contentRow(page, filename)).toBeVisible();
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= window.innerWidth
        )
      )
      .toBe(true);
    await testInfo.attach("workspace-files-mobile", {
      body: await page.screenshot({ fullPage: true }),
      contentType: "image/png",
    });
  });
});

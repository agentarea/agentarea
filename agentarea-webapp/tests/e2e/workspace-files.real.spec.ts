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
  await page.getByRole("button", { name: "New folder", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Folder name", { exact: true }).fill(name);
  await dialog
    .getByRole("button", { name: "Create folder", exact: true })
    .click();
  await expect(dialog).toBeHidden();
}

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
    const breadcrumb = page.getByRole("navigation", {
      name: "Folder path",
      exact: true,
    });
    await expect(folderTree).toBeVisible();
    await expect(
      folderTree.getByText("All files", { exact: true })
    ).toBeVisible();
    await expect(page.getByPlaceholder("Search this folder")).toBeVisible();

    await createFolder(page, "Materials");
    await contentRow(page, "Materials")
      .getByText("Materials", { exact: true })
      .click();
    await expect(
      breadcrumb.getByText("Materials", { exact: true })
    ).toBeVisible();

    await createFolder(page, "Drafts");
    await expect(contentRow(page, "Drafts")).toBeVisible();

    // Re-fetch the root from the server before navigating back to the empty
    // child. This proves folders survive beyond the creating page's state.
    await page.reload({ waitUntil: "domcontentloaded" });
    await breadcrumb.getByText("All files", { exact: true }).click();
    await contentRow(page, "Materials")
      .getByText("Materials", { exact: true })
      .click();
    await expect(contentRow(page, "Drafts")).toBeVisible();

    // The tree and the contents table must drive the same current folder.
    await folderTree.getByText("All files", { exact: true }).click();
    await expect(contentRow(page, "Materials")).toBeVisible();
    await folderTree.getByText("Materials", { exact: true }).click();
    await contentRow(page, "Drafts")
      .getByText("Drafts", { exact: true })
      .click();
    await expect(breadcrumb.getByText("Drafts", { exact: true })).toBeVisible();

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
    const preview = page.getByRole("dialog");
    await expect(preview).toBeVisible();
    await expect(
      preview.getByText(contents.trim(), { exact: true })
    ).toBeVisible({
      timeout: 20_000,
    });
    await page.keyboard.press("Escape");
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

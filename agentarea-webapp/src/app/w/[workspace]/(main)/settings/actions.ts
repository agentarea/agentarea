"use server";

import { revalidatePath } from "next/cache";
import { getTranslations } from "next-intl/server";
import {
  deleteWorkspaceLogo,
  exportWorkspaceConfig,
  uploadWorkspaceLogo,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export async function exportWorkspaceAction(): Promise<
  { data: string; error?: never } | { data?: never; error: string }
> {
  const result = await exportWorkspaceConfig();
  if (result.error || typeof result.data !== "string") {
    const t = await getTranslations("SettingsPage.workspace");
    return { error: apiErrorMessage(result, t("exportFailed")) };
  }
  return { data: result.data };
}

export async function uploadWorkspaceLogoAction(
  formData: FormData
): Promise<{ error?: string }> {
  const file = formData.get("file");
  if (!(file instanceof File)) {
    throw new Error("uploadWorkspaceLogoAction expects a file under 'file'");
  }
  const result = await uploadWorkspaceLogo(file);
  if (result.error || !result.data) {
    const t = await getTranslations("SettingsPage.workspace");
    return { error: apiErrorMessage(result, t("logoUploadFailed")) };
  }
  // The switcher in the root layout draws the logo.
  revalidatePath("/", "layout");
  return {};
}

export async function deleteWorkspaceLogoAction(): Promise<{ error?: string }> {
  const result = await deleteWorkspaceLogo();
  if (result.error || !result.data) {
    const t = await getTranslations("SettingsPage.workspace");
    return { error: apiErrorMessage(result, t("logoRemoveFailed")) };
  }
  revalidatePath("/", "layout");
  return {};
}

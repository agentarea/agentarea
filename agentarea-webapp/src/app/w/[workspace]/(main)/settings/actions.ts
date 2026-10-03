"use server";

import { getTranslations } from "next-intl/server";
import { exportWorkspaceConfig } from "@/lib/api";
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

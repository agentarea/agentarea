"use server";

import { exportWorkspace as exportWorkspaceAPI, importWorkspace as importWorkspaceAPI } from "@/lib/api";

export async function exportWorkspaceAction() {
  const { data, error } = await exportWorkspaceAPI();
  if (error) {
    return { error: (error as any).detail?.[0]?.msg || "Failed to export workspace" };
  }
  return { data };
}

export async function importWorkspaceAction(formData: FormData) {
  const config = formData.get("config") as string;
  const skipMissing = formData.get("skip_missing_dependencies") === "true";
  const overrideExisting = formData.get("override_existing") === "true";

  if (!config) {
    return { error: "Configuration is required" };
  }

  const { data, error } = await importWorkspaceAPI({
    config,
    skip_missing_dependencies: skipMissing,
    override_existing: overrideExisting,
  });

  if (error) {
    return { error: (error as any).detail?.[0]?.msg || "Failed to import workspace" };
  }

  return { data };
}

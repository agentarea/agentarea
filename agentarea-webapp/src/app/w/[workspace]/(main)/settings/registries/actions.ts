"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type { ZodError } from "zod";
import type {
  AgentareaApiApiV1RegistriesSyncResponse,
  WorkspaceRegistryRemoved,
} from "@/api/client/types.gen";
import {
  zWorkspaceRegistryCreate,
  zWorkspaceRegistryUpdate,
} from "@/api/client/zod.gen";
import {
  createWorkspaceRegistry,
  deleteWorkspaceRegistry,
  syncWorkspaceRegistry,
  updateWorkspaceRegistry,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";
import {
  toRegistryCreate,
  toRegistryUpdate,
  type RegistryFormValues,
} from "./registry-form";

export type RegistrySaveResult =
  | { ok: true }
  | { ok: false; message: string; errors?: Record<string, string> };

export type RegistryActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; message: string };

function fieldErrors(error: ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues) {
    const field = String(issue.path[0] ?? "_form");
    errors[field] ??= issue.message;
  }
  return errors;
}

async function refreshRegistries() {
  revalidatePath(await requestWorkspacePath("/settings/registries"));
}

export async function createRegistryAction(
  form: RegistryFormValues
): Promise<RegistrySaveResult> {
  const t = await getTranslations("Registries.errors");
  const parsed = zWorkspaceRegistryCreate.safeParse(toRegistryCreate(form));
  if (!parsed.success) {
    return {
      ok: false,
      message: t("invalid"),
      errors: fieldErrors(parsed.error),
    };
  }
  const result = await createWorkspaceRegistry(parsed.data);
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("createFailed")) };
  }
  await refreshRegistries();
  return { ok: true };
}

export async function updateRegistryAction(
  registryId: string,
  form: RegistryFormValues
): Promise<RegistrySaveResult> {
  const t = await getTranslations("Registries.errors");
  const parsed = zWorkspaceRegistryUpdate.safeParse(toRegistryUpdate(form));
  if (!parsed.success) {
    return {
      ok: false,
      message: t("invalid"),
      errors: fieldErrors(parsed.error),
    };
  }
  const result = await updateWorkspaceRegistry(registryId, parsed.data);
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("updateFailed")) };
  }
  await refreshRegistries();
  return { ok: true };
}

export async function deleteRegistryAction(
  registryId: string
): Promise<RegistryActionResult<WorkspaceRegistryRemoved>> {
  const t = await getTranslations("Registries.errors");
  const result = await deleteWorkspaceRegistry(registryId);
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("deleteFailed")) };
  }
  await refreshRegistries();
  return { ok: true, data: result.data };
}

export async function syncRegistryAction(
  registryId: string
): Promise<RegistryActionResult<AgentareaApiApiV1RegistriesSyncResponse>> {
  const t = await getTranslations("Registries.errors");
  const result = await syncWorkspaceRegistry(registryId);
  // A failed sync is also recorded on the registry (last_sync_error), so the
  // row shows it after the refresh either way.
  await refreshRegistries();
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("syncFailed")) };
  }
  return { ok: true, data: result.data };
}

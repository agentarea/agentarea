"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type { ZodError } from "zod";
import { zEgressExitCreate, zEgressExitUpdate } from "@/api/client/zod.gen";
import {
  createEgressExit,
  deleteEgressExit,
  updateEgressExit,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";
import {
  toEgressExitCreate,
  toEgressExitUpdate,
  type EgressExitFormValues,
} from "./egress-exit-form";

export type EgressExitSaveResult =
  | { ok: true }
  | { ok: false; message: string; errors?: Record<string, string> };

function fieldErrors(error: ZodError): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const issue of error.issues) {
    const field = String(issue.path[0] ?? "_form");
    errors[field] ??= issue.message;
  }
  return errors;
}

async function refreshEgressExits() {
  revalidatePath(await requestWorkspacePath("/settings/egress-exits"));
}

export async function createEgressExitAction(
  form: EgressExitFormValues
): Promise<EgressExitSaveResult> {
  const t = await getTranslations("EgressExits.errors");
  const parsed = zEgressExitCreate.safeParse(toEgressExitCreate(form));
  if (!parsed.success) {
    return {
      ok: false,
      message: t("invalid"),
      errors: fieldErrors(parsed.error),
    };
  }
  const result = await createEgressExit(parsed.data);
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("createFailed")) };
  }
  await refreshEgressExits();
  return { ok: true };
}

export async function updateEgressExitAction(
  exitId: string,
  form: EgressExitFormValues
): Promise<EgressExitSaveResult> {
  const t = await getTranslations("EgressExits.errors");
  const parsed = zEgressExitUpdate.safeParse(toEgressExitUpdate(form));
  if (!parsed.success) {
    return {
      ok: false,
      message: t("invalid"),
      errors: fieldErrors(parsed.error),
    };
  }
  const result = await updateEgressExit(exitId, parsed.data);
  if (result.error || !result.data) {
    return { ok: false, message: apiErrorMessage(result, t("updateFailed")) };
  }
  await refreshEgressExits();
  return { ok: true };
}

export async function deleteEgressExitAction(
  exitId: string
): Promise<{ ok: true } | { ok: false; message: string }> {
  const t = await getTranslations("EgressExits.errors");
  const result = await deleteEgressExit(exitId);
  if (result.error) {
    return { ok: false, message: apiErrorMessage(result, t("deleteFailed")) };
  }
  await refreshEgressExits();
  return { ok: true };
}

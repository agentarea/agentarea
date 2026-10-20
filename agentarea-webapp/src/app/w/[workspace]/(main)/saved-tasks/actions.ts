"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type {
  TaskDefinitionCreate,
  TaskDefinitionUpdate,
} from "@/api/client/types.gen";
import {
  zTaskDefinitionCreate,
  zTaskDefinitionUpdate,
} from "@/api/client/zod.gen";
import {
  createTaskDefinition,
  deleteTaskDefinition,
  runTaskDefinition,
  updateTaskDefinition,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

export type SavedTaskFormState = {
  errors?: { [key: string]: string[] };
  /** Set once saved: the saved task, so the form can open it. */
  definitionId?: string;
};

function parseParameters(raw: FormDataEntryValue | null): unknown {
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function fieldErrors(issues: { path: PropertyKey[]; message: string }[]) {
  const errors: { [key: string]: string[] } = {};
  for (const issue of issues) {
    const path = issue.path.join(".") || "_form";
    (errors[path] ??= []).push(issue.message);
  }
  return errors;
}

/** Create a saved task, or change the one the form names with `id`. */
export async function saveSavedTaskAction(
  _prevState: SavedTaskFormState,
  formData: FormData
): Promise<SavedTaskFormState> {
  const t = await getTranslations("SavedTasksPage");
  const parameters = parseParameters(formData.get("parameters"));
  if (
    !parameters ||
    typeof parameters !== "object" ||
    Array.isArray(parameters)
  ) {
    return { errors: { parameters: [t("form.invalidParameters")] } };
  }
  const body = {
    name: formData.get("name"),
    description: formData.get("description"),
    agent_id: formData.get("agent_id"),
    parameters,
  };
  const id = formData.get("id");

  if (typeof id === "string" && id) {
    const validated = zTaskDefinitionUpdate.safeParse(body);
    if (!validated.success)
      return { errors: fieldErrors(validated.error.issues) };
    const result = await updateTaskDefinition(
      id,
      validated.data as TaskDefinitionUpdate
    );
    if (!result.data) {
      return { errors: { _form: [apiErrorMessage(result, t("saveFailed"))] } };
    }
    revalidatePath(await requestWorkspacePath("/saved-tasks"));
    revalidatePath(await requestWorkspacePath(`/saved-tasks/${id}`));
    return { definitionId: result.data.id };
  }

  const validated = zTaskDefinitionCreate.safeParse(body);
  if (!validated.success)
    return { errors: fieldErrors(validated.error.issues) };
  const result = await createTaskDefinition(
    validated.data as TaskDefinitionCreate
  );
  if (!result.data) {
    return { errors: { _form: [apiErrorMessage(result, t("saveFailed"))] } };
  }
  revalidatePath(await requestWorkspacePath("/saved-tasks"));
  return { definitionId: result.data.id };
}

/** Run the saved task now; returns the task to watch. */
export async function runSavedTaskAction(definitionId: string) {
  const result = await runTaskDefinition(definitionId);
  if (!result.data) {
    const t = await getTranslations("SavedTasksPage");
    return {
      success: false as const,
      error: apiErrorMessage(result, t("runFailed")),
    };
  }
  return { success: true as const, taskId: result.data.id };
}

export async function deleteSavedTaskAction(definitionId: string) {
  const result = await deleteTaskDefinition(definitionId);
  if (result.error) {
    return { success: false, error: result.error, status: result.status };
  }
  revalidatePath(await requestWorkspacePath("/saved-tasks"));
  return { success: true };
}

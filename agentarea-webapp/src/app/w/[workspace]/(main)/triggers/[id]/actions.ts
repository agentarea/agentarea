"use server";

import { getTranslations } from "next-intl/server";
import {
  enableTrigger,
  disableTrigger,
  deleteTrigger,
  runTriggerNow,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export async function enableTriggerAction(triggerId: string) {
  const result = await enableTrigger(triggerId);
  if (result.error) {
    const t = await getTranslations("TriggersPage.error");
    return { success: false, error: apiErrorMessage(result, t("enableFailed")) };
  }
  return { success: true, data: result.data };
}

export async function disableTriggerAction(triggerId: string) {
  const result = await disableTrigger(triggerId);
  if (result.error) {
    const t = await getTranslations("TriggersPage.error");
    return {
      success: false,
      error: apiErrorMessage(result, t("disableFailed")),
    };
  }
  return { success: true, data: result.data };
}

export async function deleteTriggerAction(triggerId: string) {
  const result = await deleteTrigger(triggerId);
  if (result.error) {
    return { success: false, error: result.error, status: result.status };
  }
  return { success: true, data: result.data };
}

/**
 * Fire the trigger once, now. Returns the task to watch, or -- when the
 * trigger's own conditions rejected the run -- why it was skipped. A skipped
 * run is an answer about the trigger, so it is not reported as a failure.
 */
export async function runTriggerNowAction(triggerId: string) {
  const result = await runTriggerNow(triggerId);
  if (result.error || !result.data) {
    const t = await getTranslations("TriggersPage.error");
    return {
      success: false as const,
      error: apiErrorMessage(result, t("runFailed")),
    };
  }
  return {
    success: true as const,
    taskId: result.data.task_id ?? null,
    reason: result.data.reason ?? null,
  };
}

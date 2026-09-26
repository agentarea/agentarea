"use server";

import {
  enableTrigger,
  disableTrigger,
  deleteTrigger,
  runTriggerNow,
  updateTrigger,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export async function enableTriggerAction(triggerId: string) {
  const { data, error } = await enableTrigger(triggerId);
  if (error) {
    return { success: false, error: "Failed to enable trigger" };
  }
  return { success: true, data };
}

export async function disableTriggerAction(triggerId: string) {
  const { data, error } = await disableTrigger(triggerId);
  if (error) {
    return { success: false, error: "Failed to disable trigger" };
  }
  return { success: true, data };
}

export async function deleteTriggerAction(triggerId: string) {
  const { data, error } = await deleteTrigger(triggerId);
  if (error) {
    return { success: false, error: "Failed to delete trigger" };
  }
  return { success: true, data };
}

/**
 * Fire the trigger once, now. Returns the task to watch, or -- when the
 * trigger's own conditions rejected the run -- why it was skipped. A skipped
 * run is an answer about the trigger, so it is not reported as a failure.
 */
export async function runTriggerNowAction(triggerId: string) {
  const result = await runTriggerNow(triggerId);
  if (result.error || !result.data) {
    return {
      success: false as const,
      error: apiErrorMessage(result, "Failed to run trigger"),
    };
  }
  return {
    success: true as const,
    taskId: result.data.task_id ?? null,
    reason: result.data.reason ?? null,
  };
}

export async function updateTriggerAction(
  triggerId: string,
  body: {
    name?: string;
    config?: Record<string, unknown>;
    task_parameters?: Record<string, unknown>;
    failure_threshold?: number;
  }
) {
  const { data, error } = await updateTrigger(triggerId, body);
  if (error) {
    return { success: false, error: "Failed to update trigger" };
  }
  return { success: true, data };
}

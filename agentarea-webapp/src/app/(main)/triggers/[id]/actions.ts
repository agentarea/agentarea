"use server";

import {
  enableTrigger,
  disableTrigger,
  deleteTrigger,
  updateTrigger,
} from "@/lib/api";

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

export async function updateTriggerAction(
  triggerId: string,
  body: {
    name?: string;
    config?: Record<string, any>;
    task_parameters?: Record<string, any>;
    failure_threshold?: number;
  }
) {
  const { data, error } = await updateTrigger(triggerId, body);
  if (error) {
    return { success: false, error: "Failed to update trigger" };
  }
  return { success: true, data };
}

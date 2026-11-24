"use server";

import { runTaskDefinition } from "@/lib/api";

/** Runs a saved task as saved; the id of the task it started, or null when refused. */
export async function runSavedTask(
  definitionId: string
): Promise<string | null> {
  const { data, error } = await runTaskDefinition(definitionId);
  if (error || !data) return null;
  return data.id;
}

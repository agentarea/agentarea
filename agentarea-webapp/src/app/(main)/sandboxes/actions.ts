"use server";

import { listSandboxes } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

export async function listSandboxesAction() {
  const result = await listSandboxes();
  if (result.error || !result.data) {
    return {
      data: null,
      error: apiErrorMessage(result, "Sandbox inventory is unavailable"),
    };
  }
  return { data: result.data, error: null };
}

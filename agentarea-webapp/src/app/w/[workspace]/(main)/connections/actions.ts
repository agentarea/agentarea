"use server";

import type { McpServerInstanceCreate } from "@/api/client/types.gen";
import { createMCPServerInstance as createMCPServerInstanceAPI } from "@/lib/api";

export async function createMCPServerInstance(
  instance: McpServerInstanceCreate
) {
  return await createMCPServerInstanceAPI(instance);
}

"use server";

import { createMCPServerInstance as createMCPServerInstanceAPI } from "@/lib/api";
import type { components } from "@/api/schema";

export async function createMCPServerInstance(
  instance: components["schemas"]["MCPServerInstanceCreateRequest"]
) {
  return await createMCPServerInstanceAPI(instance);
}

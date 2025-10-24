"use server";

import type { components } from "@/api/schema";
import { createMCPServerInstance as createMCPServerInstanceAPI } from "@/lib/api";

export async function createMCPServerInstance(
  instance: components["schemas"]["MCPServerInstanceCreateRequest"]
) {
  return await createMCPServerInstanceAPI(instance);
}

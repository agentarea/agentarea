"use server";

import { listSandboxes } from "@/lib/api";

export async function listSandboxesAction() {
  const { data, error } = await listSandboxes();
  if (error || !data) {
    return { data: null, error: "Sandbox inventory is unavailable" };
  }
  return { data, error: null };
}

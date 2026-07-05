"use server";

import {
  deleteMCPServerInstance,
  verifyMCPServerInstance,
} from "@/lib/api";

export async function verifyInstance(instanceId: string) {
  return verifyMCPServerInstance(instanceId);
}

export async function deleteInstance(instanceId: string) {
  return deleteMCPServerInstance(instanceId);
}

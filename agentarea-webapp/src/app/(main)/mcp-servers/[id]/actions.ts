"use server";

import {
  startMCPServerInstance,
  stopMCPServerInstance,
  deleteMCPServerInstance,
} from "@/lib/api";

export async function startInstance(instanceId: string) {
  return startMCPServerInstance(instanceId);
}

export async function stopInstance(instanceId: string) {
  return stopMCPServerInstance(instanceId);
}

export async function deleteInstance(instanceId: string) {
  return deleteMCPServerInstance(instanceId);
}

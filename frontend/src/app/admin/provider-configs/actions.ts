"use server";

import { deleteProviderConfig as deleteProviderConfigAPI } from "@/lib/api";

export async function deleteProviderConfig(configId: string) {
  return await deleteProviderConfigAPI(configId);
}

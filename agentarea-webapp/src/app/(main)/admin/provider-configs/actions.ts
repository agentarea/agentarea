"use server";

import {
  deleteProviderConfig as deleteProviderConfigAPI,
  discoverModels as discoverModelsAPI,
} from "@/lib/api";

export async function deleteProviderConfig(configId: string) {
  return await deleteProviderConfigAPI(configId);
}

export async function discoverModels(configId: string) {
  return await discoverModelsAPI(configId);
}

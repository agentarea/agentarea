"use server";

import { createAPIKey as createAPIKeyAPI, revokeAPIKey as revokeAPIKeyAPI } from "@/lib/api";

export async function createAPIKeyAction(formData: FormData) {
  const name = formData.get("name") as string;
  const expiresInDays = formData.get("expires_in_days") as string;

  if (!name) {
    return { error: "Name is required" };
  }

  const { data, error } = await createAPIKeyAPI({
    name,
    ...(expiresInDays ? { expires_in_days: parseInt(expiresInDays, 10) } : {}),
  });

  if (error) {
    return { error: (error as any).detail?.[0]?.msg || "Failed to create API key" };
  }

  return { data };
}

export async function revokeAPIKeyAction(tokenId: string) {
  const { data, error } = await revokeAPIKeyAPI(tokenId);

  if (error) {
    return { error: (error as any).detail?.[0]?.msg || "Failed to revoke API key" };
  }

  return { data };
}

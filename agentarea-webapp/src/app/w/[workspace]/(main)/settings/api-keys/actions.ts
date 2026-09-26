"use server";

import type { ApiKeyCreateRequest } from "@/api/client/types.gen";
import { zApiKeyCreateRequest } from "@/api/client/zod.gen";
import { createAPIKey as createAPIKeyAPI, revokeAPIKey as revokeAPIKeyAPI } from "@/lib/api";

export async function createAPIKeyAction(input: ApiKeyCreateRequest) {
  const body = { ...input, name: input.name.trim() };

  if (!body.name) {
    return { error: "Name is required" };
  }

  const parsed = zApiKeyCreateRequest.safeParse(body);

  if (!parsed.success) {
    return { error: parsed.error.issues[0]?.message || "Invalid API key" };
  }

  const apiKeyBody: { name: string; expires_in_days?: number } = {
    name: parsed.data.name,
    ...(parsed.data.expires_in_days == null
      ? {}
      : { expires_in_days: parsed.data.expires_in_days }),
  };

  const { data, error } = await createAPIKeyAPI(apiKeyBody);

  if (error) {
    return { error: (error as { detail?: Array<{ msg: string }> }).detail?.[0]?.msg || "Failed to create API key" };
  }

  return { data };
}

export async function revokeAPIKeyAction(tokenId: string) {
  const { data, error } = await revokeAPIKeyAPI(tokenId);

  if (error) {
    return { error: (error as { detail?: Array<{ msg: string }> }).detail?.[0]?.msg || "Failed to revoke API key" };
  }

  return { data };
}

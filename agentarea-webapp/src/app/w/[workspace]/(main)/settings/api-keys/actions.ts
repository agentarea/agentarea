"use server";

import type { ApiKeyCreateRequest } from "@/api/client/types.gen";
import { zApiKeyCreateRequest } from "@/api/client/zod.gen";
import { createAPIKey as createAPIKeyAPI, revokeAPIKey as revokeAPIKeyAPI } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";

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

  const result = await createAPIKeyAPI(apiKeyBody);

  if (result.error) {
    return { error: formatApiError(result.error) };
  }

  return { data: result.data };
}

export async function revokeAPIKeyAction(tokenId: string) {
  const result = await revokeAPIKeyAPI(tokenId);

  if (result.error) {
    return { error: formatApiError(result.error) };
  }

  return { data: result.data };
}

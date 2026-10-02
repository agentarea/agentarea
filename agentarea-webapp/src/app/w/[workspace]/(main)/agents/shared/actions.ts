"use server";

import { readAgentCard } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";

export async function readAgentCardAction(url: string) {
  const result = await readAgentCard(url);
  if (result.error || !result.data) {
    return { error: formatApiError(result.error) };
  }
  return { data: result.data };
}

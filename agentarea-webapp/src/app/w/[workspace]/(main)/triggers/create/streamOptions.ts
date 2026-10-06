import type { StreamResponse } from "@/api/client/types.gen";
import { listStreams } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";

/** The streams a stream trigger can bind to, or why they could not be listed. */
export type StreamOptions = { items: StreamResponse[]; error: string | null };

export async function loadStreamOptions(
  failureLabel: string
): Promise<StreamOptions> {
  const result = await listStreams();
  if (result.data) return { items: result.data, error: null };
  return { items: [], error: apiErrorMessage(result, failureLabel) };
}

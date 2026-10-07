"use server";

import { revalidatePath } from "next/cache";
import { getTranslations } from "next-intl/server";
import type {
  WebhookSourceCreate,
  WebhookSourceCreated,
} from "@/api/client/types.gen";
import { zWebhookSourceCreate } from "@/api/client/zod.gen";
import { createStreamSource, deleteStreamSource } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

export type CreateSourceResult =
  | { error: string; source?: undefined }
  | { error: null; source: WebhookSourceCreated };

export async function createStreamSourceAction(
  streamId: string,
  input: WebhookSourceCreate
): Promise<CreateSourceResult> {
  const t = await getTranslations("EventsPage.sources");
  const body = zWebhookSourceCreate.parse(input);
  const result = await createStreamSource(streamId, body);
  if (result.error || !result.data) {
    return { error: apiErrorMessage(result, t("createFailed")) };
  }
  revalidatePath(await requestWorkspacePath(`/events/${streamId}`));
  return { error: null, source: result.data };
}

export async function deleteStreamSourceAction(
  streamId: string,
  sourceId: string
) {
  const result = await deleteStreamSource(streamId, sourceId);
  if (!result.error) {
    revalidatePath(await requestWorkspacePath(`/events/${streamId}`));
  }
  return result;
}

"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type { SourceCreate, SourceCreated } from "@/api/client/types.gen";
import { zSourceCreate } from "@/api/client/zod.gen";
import { createStreamSource, deleteStreamSource } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

export type CreateSourceResult =
  | { error: string; source?: undefined }
  | { error: null; source: SourceCreated };

export async function createStreamSourceAction(
  streamId: string,
  input: SourceCreate
): Promise<CreateSourceResult> {
  const t = await getTranslations("EventsPage.sources");
  const body = zSourceCreate.parse(input);
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

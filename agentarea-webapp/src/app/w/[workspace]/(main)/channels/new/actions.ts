"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import {
  zSourceCreate,
  zStreamCreate,
  zTriggerCreate,
} from "@/api/client/zod.gen";
import {
  createStream,
  createStreamSource,
  createTrigger,
  deleteStream,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { DEFAULT_SESSION_IDLE_TIMEOUT } from "@/lib/sourceTypes";
import { requestWorkspacePath } from "@/lib/workspace-request";
import type { ChannelRequest } from "./channelRequest";

export type CreateChannelResult =
  | { error: string }
  | {
      error: null;
      triggerId: string;
      webhookUrl: string | null;
      issued: Record<string, string>;
    };

/**
 * Make a channel: a stream, the source feeding it and a trigger binding it to
 * the agent. A step that fails takes the stream it made with it, so a refused
 * channel leaves nothing behind.
 */
export async function createChannelAction(
  request: ChannelRequest
): Promise<CreateChannelResult> {
  const t = await getTranslations("ChannelsPage.create");
  const stream = await createStream(zStreamCreate.parse(request.stream));
  if (!stream.data) {
    return { error: apiErrorMessage(stream, t("streamFailed")) };
  }
  const streamId = stream.data.id;

  const undo = async (reason: string): Promise<CreateChannelResult> => {
    const removed = await deleteStream(streamId);
    if (removed.error) {
      const left = apiErrorMessage(removed, t("undoFailed", { streamId }));
      return { error: `${reason}. ${left}` };
    }
    return { error: reason };
  };

  const source = await createStreamSource(
    streamId,
    zSourceCreate.parse(request.source)
  );
  if (!source.data) {
    return undo(apiErrorMessage(source, t("sourceFailed")));
  }

  const trigger = await createTrigger(
    zTriggerCreate.parse({
      name: request.name,
      description: "",
      trigger_type: "stream",
      agent_id: request.agentId,
      stream_id: streamId,
      session: { continue: true, idle_timeout: DEFAULT_SESSION_IDLE_TIMEOUT },
    })
  );
  if (!trigger.data) {
    return undo(apiErrorMessage(trigger, t("triggerFailed")));
  }

  revalidatePath(await requestWorkspacePath("/channels"));
  revalidatePath(await requestWorkspacePath("/triggers"));
  return {
    error: null,
    triggerId: trigger.data.id,
    webhookUrl: source.data.webhook_url ?? null,
    issued: source.data.issued ?? {},
  };
}

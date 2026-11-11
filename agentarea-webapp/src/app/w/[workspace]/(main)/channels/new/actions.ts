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

/** The trigger as checked before anything is written; its stream is not made yet. */
const zChannelTrigger = zTriggerCreate.omit({ stream_id: true });

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
  const streamBody = zStreamCreate.safeParse(request.stream);
  const sourceBody = zSourceCreate.safeParse(request.source);
  const triggerBody = zChannelTrigger.safeParse({
    name: request.name,
    description: "",
    trigger_type: "stream",
    agent_id: request.agentId,
    session: { continue: true, idle_timeout: DEFAULT_SESSION_IDLE_TIMEOUT },
  });
  if (!streamBody.success || !sourceBody.success || !triggerBody.success) {
    const issues = [streamBody, sourceBody, triggerBody].flatMap((parsed) =>
      parsed.success ? [] : parsed.error.issues
    );
    return {
      error: t("invalid", {
        detail: issues
          .map((issue) => `${issue.path.join(".")}: ${issue.message}`)
          .join("; "),
      }),
    };
  }

  const stream = await createStream(streamBody.data);
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

  const source = await createStreamSource(streamId, sourceBody.data);
  if (!source.data) {
    return undo(apiErrorMessage(source, t("sourceFailed")));
  }

  const trigger = await createTrigger({
    ...triggerBody.data,
    stream_id: streamId,
  });
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

import { useCallback } from "react";
import { createFollowupAgentTask } from "@/components/Chat/utils/createFollowupAgentTask";
import {
  cancelAgentTaskAction,
  resolveEscalationAction,
  sendTaskCommandAction,
  submitTaskInputAction,
} from "@/lib/server-actions";

export type TaskInputSecrets = Record<
  string,
  { value: string; secret_name?: string }
>;

type ActionResult = { data?: unknown; error?: unknown };

const NO_TARGET: ActionResult = { error: "No agent or task in context" };

/**
 * Single action layer for a task, bound once to (agentId, taskId).
 *
 * Every task surface (the /tasks/[id] conversation, the agent task view, the
 * workplace composer) drives the same server actions. Centralizing them here
 * means a surface can't wire a divergent subset (which is how /tasks/[id] ended
 * up unable to answer human-input requests). Consumers get stable callbacks.
 */
export function useTaskActions(agentId: string | null, taskId: string | null) {
  const submitInput = useCallback(
    async (
      inputRequestId: string,
      answers: Record<string, unknown>,
      secrets: TaskInputSecrets = {}
    ): Promise<ActionResult> => {
      if (!agentId || !taskId) return NO_TARGET;
      return submitTaskInputAction(agentId, taskId, {
        input_request_id: inputRequestId,
        answers,
        secrets,
      });
    },
    [agentId, taskId]
  );

  const resolveEscalation = useCallback(
    async (
      escalationId: string,
      approved: boolean,
      comment = ""
    ): Promise<ActionResult> => {
      if (!agentId || !taskId) return NO_TARGET;
      return resolveEscalationAction(
        agentId,
        taskId,
        escalationId,
        approved,
        comment
      );
    },
    [agentId, taskId]
  );

  const queueMessage = useCallback(
    async (message: string): Promise<ActionResult> => {
      if (!agentId || !taskId) return NO_TARGET;
      return sendTaskCommandAction(agentId, taskId, {
        command: "queue_message",
        message,
      });
    },
    [agentId, taskId]
  );

  const cancel = useCallback(async (): Promise<ActionResult> => {
    if (!agentId || !taskId) return NO_TARGET;
    return cancelAgentTaskAction(agentId, taskId);
  }, [agentId, taskId]);

  /**
   * Start a fresh follow-up task for the same agent and return its id. The
   * create endpoint streams SSE; the task_id lands in the first chunk, so we
   * scan the stream for it and stop.
   */
  const createFollowupTask = useCallback(
    async (
      description: string,
      files: readonly File[] = []
    ): Promise<string | null> => {
      if (!agentId) return null;
      return createFollowupAgentTask(agentId, description, files);
    },
    [agentId]
  );

  return {
    submitInput,
    resolveEscalation,
    queueMessage,
    cancel,
    createFollowupTask,
  };
}

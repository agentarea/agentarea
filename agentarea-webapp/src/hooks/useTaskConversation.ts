import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { MessageComponentType } from "@/components/Chat/types";
import { processEventsToMessages } from "@/components/Chat/utils/eventProcessor";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import { useTaskActions, type TaskInputSecrets } from "@/hooks/useTaskActions";

// Statuses where the workflow is still alive and a free-text message should be
// queued for the next iteration (rather than starting a new task). "completed"
// is included on purpose: a conversational task writes "completed" after each
// reply but stays alive in its follow-up window.
const QUEUEABLE_STATUSES = ["running", "paused", "blocked", "completed"];

export interface PendingInput {
  input_request_id: string;
  questions: Array<{ id: string }>;
  allow_custom_response: boolean;
}

interface UseTaskConversationOptions {
  /** Live task status (e.g. from the task detail context). Drives routing. */
  status?: string;
}

/**
 * Single source of truth for a task's conversation: the live event feed, the
 * derived chat messages (with optimistic echoes), and the full action set.
 *
 * `sendMessage` routes by task state so callers never have to:
 *  - waiting on a structured input request -> answer it (resumes the workflow)
 *  - task still live -> queue the message for the next iteration
 *  - task finished -> start a follow-up task and navigate to it
 */
export function useTaskConversation(
  agentId: string | null,
  taskId: string | null,
  options: UseTaskConversationOptions = {},
) {
  const router = useRouter();
  const status = options.status ?? "";

  const { events, loading, connected, refresh } = useTaskEvents(
    agentId,
    taskId,
    { includeHistory: true, autoConnect: true },
  );

  const actions = useTaskActions(agentId, taskId);

  const [optimistic, setOptimistic] = useState<MessageComponentType[]>([]);

  const baseMessages = useMemo(() => {
    if (!agentId || !taskId) return [];
    return processEventsToMessages(
      events.map((e) => ({ type: e.type, timestamp: e.timestamp, data: e.data })),
      { taskId, agentId },
    );
  }, [events, agentId, taskId]);

  // Merge optimistic user echoes, dropping any already confirmed by an event.
  const messages = useMemo(() => {
    const confirmed = new Set(
      baseMessages
        .filter((m) => m.type === "user_message")
        .map((m) => (m.data as { content?: string }).content),
    );
    const pending = optimistic.filter(
      (m) => !confirmed.has((m.data as { content?: string }).content),
    );
    return [...baseMessages, ...pending];
  }, [baseMessages, optimistic]);

  // An unanswered structured input request only exists while the task is
  // actually paused on it; once answered the status flips away.
  const pendingInput = useMemo<PendingInput | null>(() => {
    if (status !== "waiting_for_input") return null;
    const last = [...baseMessages]
      .reverse()
      .find((m) => m.type === "input_request");
    if (!last) return null;
    const d = last.data as {
      input_request_id: string;
      questions?: Array<{ id: string }>;
      allow_custom_response?: boolean;
    };
    return {
      input_request_id: d.input_request_id,
      questions: Array.isArray(d.questions) ? d.questions : [],
      allow_custom_response: d.allow_custom_response !== false,
    };
  }, [status, baseMessages]);

  const isActive =
    QUEUEABLE_STATUSES.includes(status) || status === "waiting_for_input";

  const addOptimistic = useCallback(
    (content: string) => {
      setOptimistic((prev) => [
        ...prev,
        {
          type: "user_message",
          data: {
            id: `optimistic-${Date.now()}`,
            timestamp: new Date().toISOString(),
            agent_id: agentId ?? "",
            event_type: "MessageQueued",
            content,
          },
        } as MessageComponentType,
      ]);
    },
    [agentId],
  );

  const removeOptimistic = useCallback((content: string) => {
    setOptimistic((prev) =>
      prev.filter(
        (m) =>
          m.type !== "user_message" ||
          (m.data as { content?: string }).content !== content,
      ),
    );
  }, []);

  const submitInput = useCallback(
    async (
      inputRequestId: string,
      answers: Record<string, unknown>,
      secrets: TaskInputSecrets = {},
    ) => {
      const { error } = await actions.submitInput(inputRequestId, answers, secrets);
      if (error) toast.error("Failed to submit response");
    },
    [actions],
  );

  const sendMessage = useCallback(
    async (text: string) => {
      const message = text.trim();
      if (!message) return;

      // 1) Answer a pending structured input request -> resumes the workflow.
      if (pendingInput) {
        const fieldId = pendingInput.questions[0]?.id ?? "answer";
        addOptimistic(message);
        const { error } = await actions.submitInput(
          pendingInput.input_request_id,
          { [fieldId]: message },
          {},
        );
        if (error) {
          removeOptimistic(message);
          toast.error("Failed to submit response");
        }
        return;
      }

      // 2) Task still live -> queue for the next iteration.
      if (QUEUEABLE_STATUSES.includes(status)) {
        addOptimistic(message);
        const { error } = await actions.queueMessage(message);
        if (error) {
          removeOptimistic(message);
          toast.error("Failed to send message");
        }
        return;
      }

      // 3) Task finished -> start a follow-up task and navigate to it.
      try {
        const newTaskId = await actions.createFollowupTask(message);
        if (newTaskId) router.push(`/tasks/${newTaskId}`);
        else toast.error("Failed to create new task");
      } catch (err) {
        toast.error("Failed to send message", {
          description: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [pendingInput, status, actions, addOptimistic, removeOptimistic, router],
  );

  return {
    events,
    messages,
    loading,
    connected,
    isActive,
    pendingInput,
    refresh,
    actions: {
      sendMessage,
      submitInput,
      resolveEscalation: actions.resolveEscalation,
      cancel: actions.cancel,
    },
  };
}

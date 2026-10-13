import { findPendingForm, type EventState } from "@/lib/events/reducer";

export type ComposerRoute =
  | { route: "create" }
  | {
      route: "current";
      pendingInputId: string | undefined;
      /** The task's run had closed; the message starts a new one to follow. */
      resumes: boolean;
    };

/**
 * A stopped or failed task keeps its conversation: a message continues it in a
 * new run instead of starting a task without that context.
 */
export function continuesClosedConversation(
  state: Pick<EventState, "status" | "executionStatus">
): boolean {
  return (
    state.executionStatus === "finished" &&
    (state.status === "cancelled" || state.status === "failed")
  );
}

/**
 * Each accepted task owns subsequent input and action submissions, so a
 * `task_created` for a different task replaces the one the chat holds — not
 * only the first one it ever saw.
 */
export function adoptCreatedTaskId(
  currentTaskId: string | null,
  data: Record<string, unknown> | undefined
): string | null {
  const taskId = typeof data?.task_id === "string" ? data.task_id : null;
  return taskId && taskId !== currentTaskId ? taskId : null;
}

/**
 * Where the composer's message goes: onto the current task while it is still
 * waiting for the user (an open request, or a follow-up wait) or after it was
 * stopped or failed, otherwise into a new task. Attachments always create a
 * task — the current task's queue and input contracts are text-only.
 */
export function routeComposerMessage(
  state: EventState,
  {
    currentTaskId,
    hasFiles,
  }: { currentTaskId: string | null; hasFiles: boolean }
): ComposerRoute {
  if (!currentTaskId || hasFiles) return { route: "create" };
  if (continuesClosedConversation(state)) {
    return { route: "current", pendingInputId: undefined, resumes: true };
  }
  const pendingForm = findPendingForm(state);
  if (!pendingForm && state.executionStatus !== "waiting") {
    return { route: "create" };
  }
  return {
    route: "current",
    pendingInputId:
      pendingForm?.eventType === "input.request"
        ? pendingForm.partId
        : undefined,
    resumes: false,
  };
}

interface DeliveryActionResult {
  error?: unknown;
}

interface TaskMessageActions {
  createFollowupTask: (
    description: string,
    files?: readonly File[]
  ) => Promise<string | null>;
  queueMessage: (message: string) => Promise<DeliveryActionResult>;
  submitInput: (
    inputRequestId: string,
    answers: Record<string, unknown>,
    secrets: Record<string, never>
  ) => Promise<DeliveryActionResult>;
}

export interface DeliverTaskMessageOptions {
  actions: TaskMessageActions;
  files: readonly File[];
  message: string;
  pendingInputId?: string;
  queueOnCurrentTask: boolean;
}

export type TaskMessageDelivery =
  | { route: "followup"; taskId: string | null }
  | { route: "input"; error?: unknown }
  | { route: "queue"; error?: unknown };

/**
 * Deliver composer content without discarding files on contracts that cannot
 * accept them. Attachments always use task creation; current-task queue/input
 * remains text-only.
 */
export async function deliverTaskMessage({
  actions,
  files,
  message,
  pendingInputId,
  queueOnCurrentTask,
}: DeliverTaskMessageOptions): Promise<TaskMessageDelivery> {
  if (files.length > 0 || (!pendingInputId && !queueOnCurrentTask)) {
    return {
      route: "followup",
      taskId: await actions.createFollowupTask(message, files),
    };
  }

  if (pendingInputId) {
    const { error } = await actions.submitInput(
      pendingInputId,
      { answer: message },
      {}
    );
    return { route: "input", error };
  }

  const { error } = await actions.queueMessage(message);
  return { route: "queue", error };
}

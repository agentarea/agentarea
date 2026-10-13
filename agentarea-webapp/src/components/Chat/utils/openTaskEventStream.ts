import { currentWorkspaceHeaders } from "@/lib/workspace-browser";

/**
 * Open a task's event stream after the last event the view already has, so a
 * run that a follow-up started streams on without replaying the history.
 */
export async function openTaskEventStream(
  agentId: string,
  taskId: string,
  lastEventId: string | null
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const response = await fetch(
    `/api/sse/agents/${agentId}/tasks/${taskId}/events/stream`,
    {
      headers: {
        Accept: "text/event-stream",
        ...currentWorkspaceHeaders(),
        ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
      },
    }
  );
  if (!response.ok || !response.body) {
    throw new Error(`Task event stream returned ${response.status}`);
  }
  return response.body.getReader();
}

import { currentWorkspaceHeaders } from "@/lib/workspace-browser";
import { uploadAttachments } from "./uploadAttachments";

function taskIdFromSseRecord(record: string): string | null {
  const lines = record.split(/\r?\n/);
  const eventType = lines
    .find((line) => line.startsWith("event:"))
    ?.slice("event:".length)
    .trim();
  if (eventType !== "task_created") return null;

  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (!data) return null;

  try {
    const payload = JSON.parse(data) as { task_id?: unknown };
    return typeof payload.task_id === "string" && payload.task_id
      ? payload.task_id
      : null;
  } catch {
    return null;
  }
}

async function readCreatedTaskId(
  reader: ReadableStreamDefaultReader<Uint8Array>
): Promise<string | null> {
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });

      let boundary = buffer.match(/\r?\n\r?\n/);
      while (boundary?.index !== undefined) {
        const record = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const taskId = taskIdFromSseRecord(record);
        if (taskId) {
          // This closes only the SSE transport. Task creation already dispatched
          // the workflow, and no task-control cancellation command is sent.
          await reader.cancel("task id received").catch(() => undefined);
          return taskId;
        }
        boundary = buffer.match(/\r?\n\r?\n/);
      }

      if (done) return taskIdFromSseRecord(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}

export async function createFollowupAgentTask(
  agentId: string,
  description: string,
  files: readonly File[] = []
): Promise<string | null> {
  const attachments = await uploadAttachments(files);
  const response = await fetch(`/api/agents/${agentId}/tasks/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...currentWorkspaceHeaders(),
    },
    body: JSON.stringify({
      description:
        description || "Use the attached files to complete the task.",
      parameters: {
        context: {},
        task_type: "chat",
        session_id: `chat-${Date.now()}`,
      },
      enable_agent_communication: true,
      ...(attachments.length > 0 ? { attachments } : {}),
    }),
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader) return null;
  return readCreatedTaskId(reader);
}

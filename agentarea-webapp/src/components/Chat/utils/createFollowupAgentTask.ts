import { currentWorkspaceHeaders } from "@/lib/workspace-browser";
import { uploadAttachments } from "./uploadAttachments";

export interface FollowupTaskResult {
  /** The created task's id. */
  data?: string;
  error?: unknown;
  status?: number;
}

type SseOutcome = { taskId: string } | { error: unknown } | null;

function parseSseRecord(record: string): SseOutcome {
  const lines = record.split(/\r?\n/);
  const eventType = lines
    .find((line) => line.startsWith("event:"))
    ?.slice("event:".length)
    .trim();
  if (eventType !== "task_created" && eventType !== "error") return null;

  const data = lines
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (!data) return null;

  let payload: { task_id?: unknown; error?: unknown };
  try {
    payload = JSON.parse(data) as { task_id?: unknown; error?: unknown };
  } catch {
    return eventType === "error" ? { error: data } : null;
  }
  if (eventType === "error") return { error: payload };
  return typeof payload.task_id === "string" && payload.task_id
    ? { taskId: payload.task_id }
    : null;
}

async function readCreatedTaskId(
  reader: ReadableStreamDefaultReader<Uint8Array>
): Promise<SseOutcome> {
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
        const outcome = parseSseRecord(record);
        if (outcome) {
          // This closes only the SSE transport. Task creation already dispatched
          // the workflow, and no task-control cancellation command is sent.
          await reader.cancel("task id received").catch(() => undefined);
          return outcome;
        }
        boundary = buffer.match(/\r?\n\r?\n/);
      }

      if (done) return parseSseRecord(buffer);
    }
  } finally {
    reader.releaseLock();
  }
}

async function responseError(response: Response): Promise<unknown> {
  const body = await response.text();
  if (!body) return response.statusText || `HTTP ${response.status}`;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    return body;
  }
}

export async function createFollowupAgentTask(
  agentId: string,
  description: string,
  files: readonly File[] = []
): Promise<FollowupTaskResult> {
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
    return { error: await responseError(response), status: response.status };
  }
  const reader = response.body?.getReader();
  if (!reader) return {};
  const outcome = await readCreatedTaskId(reader);
  if (!outcome) return {};
  if ("error" in outcome) return { error: outcome.error };
  return { data: outcome.taskId };
}

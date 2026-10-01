import { fillWorkspace } from "@/lib/workspace-url";

function encodeFilePath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

/** Browser URL of one file in a task's live sandbox, through the file proxy. */
export function taskSandboxFileUrl(
  agentId: string,
  taskId: string,
  path: string,
  workspaceSlug: string | null
): string {
  return fillWorkspace(
    `/api/proxy/v1/workspaces/{workspace}/agents/${encodeURIComponent(
      agentId
    )}/tasks/${encodeURIComponent(taskId)}/sandbox/files/${encodeFilePath(path)}`,
    workspaceSlug
  );
}

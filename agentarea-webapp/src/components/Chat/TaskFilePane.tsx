"use client";

import { useCallback } from "react";
import { FileViewerContent } from "@/components/files/file-viewer";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { taskSandboxFileUrl } from "@/lib/task-files";

/** A file of the task, open beside its conversation. */
export function TaskFilePane({
  agentId,
  taskId,
  path,
  onClose,
}: {
  agentId: string;
  taskId: string;
  path: string;
  onClose: () => void;
}) {
  const workspaceSlug = useWorkspaceSlug();
  const fetchUrl = useCallback(
    async (file: string) => ({
      data: taskSandboxFileUrl(agentId, taskId, file, workspaceSlug),
    }),
    [agentId, taskId, workspaceSlug]
  );
  return (
    <aside className="flex h-full w-[min(560px,45vw)] shrink-0 flex-col border-l bg-background max-md:fixed max-md:inset-0 max-md:z-40 max-md:w-full">
      <FileViewerContent
        key={path}
        file={{ path }}
        fetchUrl={fetchUrl}
        onClose={onClose}
      />
    </aside>
  );
}

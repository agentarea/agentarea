"use client";

import { useParams } from "next/navigation";
import DeleteButton from "@/components/DeleteButton";
import { deleteProjectAction } from "@/lib/server-actions";

export default function ProjectHeaderControls({ projectName }: { projectName: string }) {
  const params = useParams();
  const projectId = params.id as string;

  return (
    <div className="flex items-center gap-2 py-1">
      <DeleteButton
        size="xs"
        itemId={projectId}
        itemName={projectName}
        onDelete={deleteProjectAction}
        redirectPath="/projects"
        title="Delete Project"
        description={`Are you sure you want to delete "${projectName}"? This action cannot be undone.`}
        successMessage="Project deleted successfully"
      />
    </div>
  );
}

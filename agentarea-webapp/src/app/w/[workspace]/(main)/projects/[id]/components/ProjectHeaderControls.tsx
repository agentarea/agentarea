"use client";

import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import DeleteButton from "@/components/DeleteButton";
import { deleteProjectAction } from "@/lib/server-actions";

export default function ProjectHeaderControls({ projectName }: { projectName: string }) {
  const params = useParams();
  const projectId = params.id as string;
  const t = useTranslations("ProjectSettingsPage");

  return (
    <div className="flex items-center gap-2 py-1">
      <DeleteButton
        size="xs"
        itemId={projectId}
        itemName={projectName}
        onDelete={deleteProjectAction}
        redirectPath="/projects"
        title={t("deleteTitle")}
      />
    </div>
  );
}

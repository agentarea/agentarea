"use client";

import { useTranslations } from "next-intl";
import { useParams } from "next/navigation";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import DeleteButton from "@/components/DeleteButton";
import { Button } from "@/components/ui/button";
import { useWorkspacePathname } from "@/hooks/useWorkspaceNavigation";
import { deleteProjectAction } from "@/lib/server-actions";
import { PROJECT_FORM_ID } from "../../shared/ProjectForm";

/**
 * Right-hand controls of the project header: delete, plus "Save changes" for
 * the settings form while it is open — the same place the agent page puts it.
 */
export default function ProjectHeaderControls({
  projectName,
}: {
  projectName: string;
}) {
  const params = useParams();
  const projectId = params.id as string;
  const pathname = useWorkspacePathname();
  const onSettings = pathname?.endsWith("/settings");
  const t = useTranslations("ProjectSettingsPage");
  const tCommon = useTranslations("Common");
  // Keyed on the route: the header outlives the tabs, so it has to look the
  // form up again once the settings tab has rendered it.
  const isSubmitting = useFormSubmittingState(
    onSettings ? PROJECT_FORM_ID : ""
  );

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
      {onSettings && (
        <Button
          size="xs"
          type="submit"
          form={PROJECT_FORM_ID}
          isLoading={isSubmitting}
          disabled={isSubmitting}
        >
          {tCommon("saveChanges")}
        </Button>
      )}
    </div>
  );
}

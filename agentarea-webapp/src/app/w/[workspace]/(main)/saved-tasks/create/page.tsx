import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { listAgents } from "@/lib/api";
import { SavedTaskForm } from "../components/SavedTaskForm";
import SavedTaskHeaderControls from "../components/SavedTaskHeaderControls";

export const metadata: Metadata = {
  title: "New saved task",
};

export default async function CreateSavedTaskPage() {
  const t = await getTranslations("SavedTasksPage");
  const { data: agents } = await listAgents();

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/saved-tasks" },
          { label: t("form.createTitle") },
        ],
        controls: <SavedTaskHeaderControls />,
      }}
    >
      <SavedTaskForm agents={agents ?? []} />
    </ContentBlock>
  );
}

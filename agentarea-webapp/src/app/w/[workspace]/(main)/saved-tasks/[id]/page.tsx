import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { TaskDefinitionResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock";
import { getTaskDefinition, listAgents } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { SavedTaskForm } from "../components/SavedTaskForm";
import SavedTaskHeaderControls from "../components/SavedTaskHeaderControls";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const definition = requireApiData<TaskDefinitionResponse>(
    await getTaskDefinition(id),
    "saved task"
  );
  return { title: definition.name };
}

export default async function SavedTaskPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("SavedTasksPage");
  const [definitionResult, agentsResult] = await Promise.all([
    getTaskDefinition(id),
    listAgents(),
  ]);
  const definition = requireApiData<TaskDefinitionResponse>(
    definitionResult,
    "saved task"
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/saved-tasks" },
          { label: definition.name },
        ],
        controls: (
          <SavedTaskHeaderControls
            definition={{ id: definition.id, name: definition.name }}
          />
        ),
      }}
    >
      <SavedTaskForm
        agents={agentsResult.data ?? []}
        initialData={definition}
      />
    </ContentBlock>
  );
}

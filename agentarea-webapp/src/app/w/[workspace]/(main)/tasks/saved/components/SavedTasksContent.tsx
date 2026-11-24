import { getTranslations } from "next-intl/server";
import type { TaskDefinitionResponse } from "@/api/client/types.gen";
import { AgentAvatar } from "@/components/AgentAvatar";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { listAgents, listTaskDefinitions } from "@/lib/api";
import { unwrapSoftBreaks } from "@/lib/events/toolText";
import { RunSavedTaskButton } from "./RunSavedTaskButton";

export default async function SavedTasksContent() {
  const t = await getTranslations("TasksPage");
  const [{ data: definitions = [] }, { data: agents = [] }] = await Promise.all(
    [listTaskDefinitions(), listAgents()]
  );
  const agentName = new Map(agents.map((a) => [a.id, a.name]));

  const columns = [
    {
      header: t("savedName"),
      accessor: "name",
      rowLink: true,
      render: (name: string, d: TaskDefinitionResponse) => (
        <div className="min-w-0">
          <div className="font-medium">{name}</div>
          <div className="mt-1 max-w-xl text-xs text-muted-foreground line-clamp-2">
            {d.description}
          </div>
        </div>
      ),
    },
    {
      header: t("agent"),
      accessor: "agent_id",
      render: (agentId: string) => {
        const name = agentName.get(agentId);
        return name ? (
          <div className="flex items-center gap-2 text-sm">
            <AgentAvatar agent={{ id: agentId, name }} size="xs" />
            <span className="truncate">{name}</span>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        );
      },
    },
    {
      header: "",
      accessor: "id",
      render: (id: string) => <RunSavedTaskButton definitionId={id} />,
    },
  ];

  return (
    <GridAndTableViews
      viewMode="table"
      data={definitions}
      columns={columns}
      rowHref={(d: TaskDefinitionResponse) =>
        `/workplace?${new URLSearchParams({ agent: d.agent_id, prompt: unwrapSoftBreaks(d.description) })}`
      }
      cardContent={(d: TaskDefinitionResponse) => (
        <div className="font-medium">{d.name}</div>
      )}
      emptyState={
        <EmptyState
          title={t("savedEmptyTitle")}
          description={t("savedEmptyDescription")}
          iconsType="agent"
        />
      }
    />
  );
}

import { getFormatter, getTranslations } from "next-intl/server";
import type {
  AgentResponse,
  TaskDefinitionResponse,
} from "@/api/client/types.gen";
import { AgentIdentity } from "@/components/AgentIdentity";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { listAgents, listTaskDefinitions } from "@/lib/api";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { requireApiData } from "@/lib/server-resource";
import { parseUtcTimestamp } from "@/utils/dateUtils";

interface SavedTasksContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function SavedTasksContent({
  searchQuery = "",
  viewMode = "table",
}: SavedTasksContentProps) {
  const t = await getTranslations("SavedTasksPage");
  const tCommon = await getTranslations("Common");
  const format = await getFormatter();
  const [definitionsResult, agentsResult] = await Promise.all([
    listTaskDefinitions(),
    listAgents(),
  ]);
  const definitions = requireApiData<TaskDefinitionResponse[]>(
    definitionsResult,
    "saved tasks"
  );
  const agents = new Map(
    ((agentsResult.data ?? []) as AgentResponse[]).map((agent) => [
      agent.id,
      agent,
    ])
  );

  if (definitions.length === 0) {
    return (
      <EmptyState
        title={t("emptyTitle")}
        description={t("emptyDescription")}
        iconsType="tasks"
        action={{ label: t("create"), href: "/saved-tasks/create" }}
      />
    );
  }

  const query = searchQuery.trim().toLowerCase();
  const filtered = query
    ? definitions.filter(
        (definition) =>
          definition.name.toLowerCase().includes(query) ||
          definition.description.toLowerCase().includes(query) ||
          agents.get(definition.agent_id)?.name.toLowerCase().includes(query)
      )
    : definitions;

  const agentCell = (agentId: string) => {
    const agent = agents.get(agentId);
    return agent ? (
      <AgentIdentity agent={agent} size="xs" />
    ) : (
      <span className="text-xs text-muted-foreground">—</span>
    );
  };
  const updated = (value: string) => {
    const date = parseUtcTimestamp(value);
    return date
      ? format.relativeTime(date, { now: new Date(), style: "narrow" })
      : "—";
  };

  const columns = [
    {
      header: t("columns.name"),
      accessor: "name",
      rowLink: true,
      render: (name: unknown, definition?: TaskDefinitionResponse) => (
        <div className="min-w-0">
          <div className="font-medium">{String(name)}</div>
          {definition && (
            <div className="mt-1 max-w-md text-xs text-muted-foreground line-clamp-1">
              {definition.description}
            </div>
          )}
        </div>
      ),
    },
    {
      header: t("columns.agent"),
      accessor: "agent_id",
      render: (agentId: unknown) => agentCell(String(agentId)),
    },
    {
      header: t("columns.updated"),
      accessor: "updated_at",
      render: (value: unknown) => (
        <span className="text-xs tabular-nums text-muted-foreground">
          {updated(String(value))}
        </span>
      ),
    },
  ];

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={filtered}
      columns={columns}
      itemLink={(definition) => `/saved-tasks/${definition.id}`}
      wrapCardContent={false}
      cardContent={(definition) => (
        <LinkedCard
          href={`/saved-tasks/${definition.id}`}
          title={definition.name}
          icon={ENTITY_ICONS.savedTask}
          subtitle={agents.get(definition.agent_id)?.name}
        >
          <p className="text-xs text-muted-foreground line-clamp-2">
            {definition.description}
          </p>
        </LinkedCard>
      )}
      emptyState={
        <EmptyState
          title={t("noMatchTitle")}
          description={t("noMatchDescription", { query: searchQuery })}
          iconsType="tasks"
          action={{ label: tCommon("clearSearch"), href: "/saved-tasks" }}
        />
      }
    />
  );
}

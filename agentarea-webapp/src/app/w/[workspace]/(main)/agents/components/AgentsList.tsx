import { getTranslations } from "next-intl/server";
import { AgentAvatar } from "@/components/AgentAvatar";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import ModelBadge from "@/components/ui/model-badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import { agentPath, type Agent, type ModelInfo } from "@/types";
import type { AgentToolIcon } from "@/utils/agentToolIcons";
import AgentCard from "./AgentCard";
import { AGENT_COLUMNS, AGENTS_GRID_CLASS } from "./agentColumns";
import { AgentToolIcons } from "./AgentToolIcons";

type AgentWithToolIcons = Agent & { tool_icons?: AgentToolIcon[] };

interface AgentsListProps {
  initialAgents: AgentWithToolIcons[];
  viewMode?: string;
}

export default async function AgentsList({
  initialAgents,
  viewMode = "grid",
}: AgentsListProps) {
  const t = await getTranslations("AgentsPage");

  const renderers = {
    name: (value: string, item: Agent) => (
      <div className="flex items-center gap-2">
        <AgentAvatar agent={item} size="xs" />
        <span className="truncate font-medium">{value}</span>
      </div>
    ),
    description: (value: string) => (
      <span className="block truncate text-xs text-muted-foreground">
        {value || "-"}
      </span>
    ),
    model_info: (value: ModelInfo | null | undefined) => (
      <ModelBadge
        providerName={value?.provider_name}
        iconUrl={value?.provider_icon_url}
        modelDisplayName={value?.model_display_name}
        configName={value?.config_name}
      />
    ),
    active_task_count: (value: number) =>
      value > 0 ? (
        <StatusIndicator
          kind="running"
          size="sm"
          aria-label={`${value} ${t("activeTasks")}`}
          title={`${value} ${t("activeTasks")}`}
        >
          {value}
        </StatusIndicator>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      ),
    tools: (_value: unknown, item: AgentWithToolIcons) => {
      const toolIcons = item.tool_icons ?? [];

      if (toolIcons.length === 0) {
        return <span className="text-xs text-muted-foreground">-</span>;
      }

      return (
        <div className="flex items-center gap-2">
          <AgentToolIcons maxDisplay={3} tools={toolIcons} />
          <span className="text-xs text-muted-foreground">
            {toolIcons.length}
          </span>
        </div>
      );
    },
  };

  const agentColumns = AGENT_COLUMNS.map((column) => {
    const hideOnMobile = ["description", "model_info", "tools"].includes(
      column.accessor
    );

    return {
      accessor: column.accessor,
      header: t(column.labelKey),
      headerClassName: hideOnMobile ? "hidden md:table-cell" : undefined,
      cellClassName: cn(
        column.cellClassName,
        hideOnMobile && "hidden md:table-cell"
      ),
      rowLink: column.accessor === "name",
      render: renderers[column.accessor as keyof typeof renderers],
    };
  });

  // Built-in catalog agents are discovered via Explore, not mixed into this list.
  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={initialAgents}
      columns={agentColumns}
      rowHref={agentPath}
      tableClassName="table-fixed md:table-auto"
      wrapCardContent={false}
      gridClassName={AGENTS_GRID_CLASS}
      emptyState={null}
      cardContent={(agent) => <AgentCard agent={agent} />}
    />
  );
}

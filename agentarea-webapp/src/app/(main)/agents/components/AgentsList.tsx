"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { AgentAvatar } from "@/components/AgentAvatar";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import ModelBadge from "@/components/ui/model-badge";
import { Agent, agentPath } from "@/types";
import { AgentToolIcon } from "@/utils/agentToolIcons";
import { AGENT_COLUMNS, AGENTS_GRID_CLASS } from "./agentColumns";
import { AgentToolIcons } from "./AgentToolIcons";
import AgentCard from "./AgentCard";

type AgentWithToolIcons = Agent & { tool_icons?: AgentToolIcon[] };

interface AgentsListProps {
  initialAgents: AgentWithToolIcons[];
  viewMode?: string;
}

export default function AgentsList({
  initialAgents,
  viewMode = "grid",
}: AgentsListProps) {
  const t = useTranslations("AgentsPage");
  const router = useRouter();

  // Cell renderers keyed by accessor. The column order, labels, and widths come
  // from the shared `AGENT_COLUMNS` meta (also used by the table skeleton).
  const renderers: Record<
    string,
    (value: any, item: AgentWithToolIcons) => React.ReactNode
  > = {
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
    model_info: (value: any) => (
      <ModelBadge
        providerName={value?.provider_name}
        iconUrl={value?.provider_icon_url}
        modelDisplayName={value?.model_display_name}
        configName={value?.config_name}
      />
    ),
    active_task_count: (value: number) =>
      value > 0 ? (
        <Badge variant="blue" className="text-xs">
          {value}
        </Badge>
      ) : (
        <span className="text-xs text-muted-foreground">—</span>
      ),
    tools_config: (_value: any, item: AgentWithToolIcons) => {
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

  const agentColumns = AGENT_COLUMNS.map((column) => ({
    accessor: column.accessor,
    header: t(column.labelKey),
    cellClassName: column.cellClassName,
    render: renderers[column.accessor],
  }));

  // Render table view
  if (viewMode === "table") {
    return (
      <Table
        data={initialAgents}
        columns={agentColumns}
        onRowClick={(agent) => {
          router.push(agentPath(agent));
        }}
      />
    );
  }

  // Render grid view (default). The agents list is "Yours only" — catalog
  // (built-in) agents are discovered via Explore, not mixed into the working set.
  return (
    <div className={AGENTS_GRID_CLASS}>
      {initialAgents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  );
}

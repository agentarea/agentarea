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

  // Define table columns for agents
  const agentColumns = [
    {
      accessor: "name",
      header: t("name") || "Name",
      render: (value: string, item: Agent) => (
        <div className="flex items-center gap-2">
          <AgentAvatar agent={item} size="xs" />
          <span className="truncate font-medium">{value}</span>
        </div>
      ),
    },
    {
      accessor: "description",
      header: t("description") || "Description",
      cellClassName: "max-w-[300px]",
      render: (value: string) => (
        <span className="block truncate text-xs text-muted-foreground">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "model_info",
      header: t("model") || "Model",
      render: (value: any) => (
        <ModelBadge
          providerName={value?.provider_name}
          iconUrl={value?.provider_icon_url}
          modelDisplayName={value?.model_display_name}
          configName={value?.config_name}
        />
      ),
    },
    {
      accessor: "active_task_count",
      header: t("activeTasks") || "Active Tasks",
      render: (value: number) => (
        value > 0 ? (
          <Badge variant="blue" className="text-xs">
            {value}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        )
      ),
    },
    {
      accessor: "tools_config",
      header: t("tools") || "Tools",
      render: (value: any, item: AgentWithToolIcons) => {
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
    },
  ];

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
    <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {initialAgents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  );
}

"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import Table from "@/components/Table/Table";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import ModelBadge from "@/components/ui/model-badge";
import { Agent } from "@/types";
import { getToolAvatars } from "@/utils/toolsDisplay";
import AgentCard from "./AgentCard";

interface AgentsListProps {
  initialAgents: Agent[];
  viewMode?: string;
}

export default function AgentsList({
  initialAgents,
  viewMode = "grid",
}: AgentsListProps) {
  const t = useTranslations("AgentsPage");
  const commonT = useTranslations("Common");
  const router = useRouter();

  // Define table columns for agents
  const agentColumns = [
    {
      accessor: "name",
      header: t("name") || "Name",
      render: (value: string, item: Agent) => (
        <div className="flex items-center gap-2">
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
          modelDisplayName={value?.model_display_name}
          configName={value?.config_name}
        />
      ),
    },
    {
      accessor: "tools_config",
      header: t("tools") || "Tools",
      render: (value: any, item: Agent) => {
        const toolAvatars = getToolAvatars(item);
        const toolUrls = toolAvatars.map((tool) => ({
          imageUrl: tool.imageUrl,
        }));

        if (toolUrls.length === 0) {
          return <span className="text-xs text-muted-foreground">-</span>;
        }

        return (
          <div className="flex items-center gap-2">
            <AvatarCircles maxDisplay={3} avatarUrls={toolUrls} />
            <span className="text-xs text-muted-foreground">
              {toolAvatars.length}
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
          router.push(`/agents/${agent.id}`);
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {initialAgents.map((agent) => (
        <AgentCard key={agent.id} agent={agent} />
      ))}
    </div>
  );
}

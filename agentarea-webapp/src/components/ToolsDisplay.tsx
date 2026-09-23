"use client";

import { createElement, useEffect, useState } from "react";
import Image from "next/image";
import { AlertCircle, Globe, Plug } from "lucide-react";
import { useTranslations } from "next-intl";
import { getBuiltinToolIcon } from "@/app/(main)/agents/create/utils/builtinToolUtils";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  McpInstance,
  McpServer,
} from "@/lib/mcp/resolveMcpRef";
import {
  listMCPServerInstancesAction,
  listMCPServersAction,
  listOpenAPIConnectionsAction,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import { Agent } from "@/types/agent";
import {
  AgentToolIcon,
  OpenApiConnectionRef,
  resolveAgentToolIcons,
} from "@/utils/agentToolIcons";

interface Props {
  agent: Agent;
}

const TILE =
  "flex h-6 w-6 items-center justify-center overflow-hidden rounded-lg bg-zinc-100 p-1 transition-colors hover:bg-primary/20 dark:bg-zinc-800";

function ToolTile({ tool }: { tool: AgentToolIcon }) {
  const unresolved =
    (tool.kind === "mcp" || tool.kind === "openapi") && !tool.resolved;
  let content: React.ReactNode;
  if (tool.kind === "builtin") {
    content = createElement(getBuiltinToolIcon(tool.toolName), {
      className: "h-3.5 w-3.5 text-muted-foreground",
    });
  } else if (tool.kind === "mcp" && tool.src) {
    content = (
      <Image
        src={tool.src}
        alt={tool.label}
        width={24}
        height={24}
        className="h-full w-full rounded-sm object-contain"
      />
    );
  } else if (tool.kind === "openapi" && tool.initials) {
    content = (
      <span className="grid h-full w-full place-items-center rounded-sm bg-zinc-900 text-[8px] font-semibold leading-none text-white dark:bg-zinc-100 dark:text-zinc-950">
        {tool.initials}
      </span>
    );
  } else {
    const icon =
      tool.kind === "openapi"
        ? Globe
        : tool.kind === "agent"
          ? ENTITY_ICONS.agent
          : Plug;
    content = createElement(icon, {
      className: "h-3.5 w-3.5 text-muted-foreground",
    });
  }

  const tooltip = unresolved
    ? `${tool.label} (not connected)`
    : tool.kind === "mcp"
      ? `MCP Server: ${tool.label}`
      : tool.kind === "agent"
        ? `Agent: ${tool.label}`
        : tool.label;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className={cn(TILE, unresolved && "opacity-40")}>{content}</div>
      </TooltipTrigger>
      <TooltipContent side="top" align="center">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  );
}

export default function ToolsDisplay({ agent }: Props) {
  const t = useTranslations("AgentsPage");
  const [mcpInstances, setMcpInstances] = useState<McpInstance[]>([]);
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [openApiConnections, setOpenApiConnections] = useState<
    OpenApiConnectionRef[]
  >([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listMCPServerInstancesAction(),
      listMCPServersAction({ page_size: 100 }),
      listOpenAPIConnectionsAction(),
    ])
      .then(([instancesRes, serversRes, connectionsRes]) => {
        if (cancelled) return;
        setMcpInstances((instancesRes.data as McpInstance[]) || []);
        const serversData = serversRes.data as
          | { items?: McpServer[] }
          | McpServer[]
          | undefined;
        const servers = Array.isArray(serversData)
          ? serversData
          : serversData?.items || [];
        setMcpServers(servers);
        setOpenApiConnections(
          (connectionsRes.data as OpenApiConnectionRef[]) || []
        );
      })
      .catch(() => {
        // Icons gracefully fall back to a generic plug when the registry is
        // unavailable; failing to load it should not break the panel.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const tools = resolveAgentToolIcons(agent, {
    mcpInstances,
    mcpServers,
    openApiConnections,
  });

  if (tools.length === 0) {
    return (
      <Badge size="sm" variant="yellow">
        <AlertCircle className="mr-1 h-3 w-3" />
        {t("noToolsConf")}
      </Badge>
    );
  }

  return (
    <TooltipProvider>
      <div className="flex flex-wrap gap-1">
        {tools.map((tool, index) => (
          <ToolTile key={index} tool={tool} />
        ))}
      </div>
    </TooltipProvider>
  );
}

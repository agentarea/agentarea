"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Box,
  Cloud,
  Command,
  Container,
  Cpu,
  Database,
  Folder,
  Github,
  Globe,
  Mail,
  MessageSquare,
  Search,
  Server,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import EntityMark from "@/components/EntityMark";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  getMCPConnectionIconSrc,
  openApiIdentity,
} from "@/lib/entity-identity";
import { getOpenApiConnectionDisplayStatus } from "@/lib/status";
import { cn } from "@/lib/utils";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import {
  CONNECTION_TYPE_CONFIG,
  getConnectionTypes,
  getMCPConnectionTitle,
  getMCPInstanceToolCount,
  TRANSPORT_LABEL,
} from "../utils";
import { getMcpConnectionState, getOpenApiConnectionState } from "../state";
import type { ConnectionUsage } from "../usage";

interface MCPServerSpecCardProps {
  server: MCPServer;
  onConfigure?: (server: MCPServer) => void;
}

interface MCPInstanceCardProps {
  instance: MCPInstance;
  serverSpec?: MCPServer;
  /** Per-connection usage; omitted when the caller has no agent data. */
  usage?: ConnectionUsage;
}

function getMCPIcon(name: string) {
  const lower = name.toLowerCase();
  if (
    lower.includes("postgres") ||
    lower.includes("sql") ||
    lower.includes("mongo") ||
    lower.includes("redis")
  )
    return Database;
  if (lower.includes("file") || lower.includes("fs")) return Folder;
  if (lower.includes("git")) return Github;
  if (
    lower.includes("fetch") ||
    lower.includes("http") ||
    lower.includes("web") ||
    lower.includes("browser")
  )
    return Globe;
  if (
    lower.includes("slack") ||
    lower.includes("discord") ||
    lower.includes("chat")
  )
    return MessageSquare;
  if (
    lower.includes("drive") ||
    lower.includes("cloud") ||
    lower.includes("aws") ||
    lower.includes("s3")
  )
    return Cloud;
  if (lower.includes("docker") || lower.includes("kube")) return Container;
  if (
    lower.includes("terminal") ||
    lower.includes("shell") ||
    lower.includes("bash")
  )
    return Terminal;
  if (lower.includes("memory")) return Cpu;
  if (
    lower.includes("search") ||
    lower.includes("brave") ||
    lower.includes("google")
  )
    return Search;
  if (
    lower.includes("mail") ||
    lower.includes("gmail") ||
    lower.includes("outlook")
  )
    return Mail;
  if (
    lower.includes("linear") ||
    lower.includes("jira") ||
    lower.includes("project")
  )
    return Command;
  if (lower.includes("obsidian") || lower.includes("notion")) return Box;

  return Server;
}

export function MCPInstanceCard({
  instance,
  serverSpec,
  usage,
}: MCPInstanceCardProps) {
  const t = useTranslations("MCPServersPage.table");
  const tState = useTranslations("MCPServersPage.state");
  const toolCount = getMCPInstanceToolCount(instance);
  const connectionState = getMcpConnectionState({
    verification: instance.verification,
    last_dispatch: instance.last_dispatch,
    toolCount,
  });
  // Granted beats available: a card that brags "400 tools" hides whether any
  // agent holds them, which is the fact worth scanning for.
  const granted = usage
    ? usage.grantedTools === null
      ? t("allTools")
      : `${usage.grantedTools} / ${toolCount}`
    : null;
  const facts: CardFact[] = [
    {
      key: "tools",
      icon: ENTITY_ICONS.tool,
      value: granted ?? String(toolCount),
      label: granted
        ? t("toolsGranted", { granted })
        : t("toolsTotal", { total: toolCount }),
    },
  ];
  if (usage) {
    facts.push({
      key: "agents",
      icon: ENTITY_ICONS.agent,
      value: String(usage.agents),
      label:
        usage.agents === 0 ? t("unused") : t("agentCount", { count: usage.agents }),
    });
  }

  const typeLabel = TRANSPORT_LABEL[instance.transport];

  const providerIcon = getMCPConnectionIconSrc(instance, serverSpec);
  const displayTitle = getMCPConnectionTitle(instance, serverSpec);

  return (
    <LinkedCard
      href={`/connections/${instance.id}`}
      title={displayTitle}
      icon={providerIcon || getMCPIcon(instance.name)}
      type="view"
      subtitle={
        <CardSubtitle
          status={
            <StatusIndicator size="sm" kind={connectionState.kind}>
              {tState(connectionState.key)}
            </StatusIndicator>
          }
          // The type last: it is the one to drop when the card is narrow.
          facts={[...facts, { key: "type", value: typeLabel, label: typeLabel }]}
        />
      }
    />
  );
}

interface CardFact {
  key: string;
  /** With an icon the value is a short count; the label spells it out. */
  icon?: LucideIcon;
  value: string;
  label: string;
}

/**
 * One line, so every card keeps the same height: the status, then the facts
 * as icon + count like the project cards, the words in the tooltip. A fact
 * that does not fit wraps onto a second line the box clips, so it is left out
 * whole rather than cut to "un…".
 */
function CardSubtitle({
  status,
  badge,
  facts,
}: {
  status: ReactNode;
  badge?: ReactNode;
  facts: CardFact[];
}) {
  return (
    <div className="flex w-full min-w-0 items-center gap-2">
      <span className="shrink-0 whitespace-nowrap">{status}</span>
      {badge && <span className="shrink-0">{badge}</span>}
      {facts.length > 0 && (
        <span className="flex h-4 min-w-0 flex-1 flex-wrap gap-x-2.5 overflow-hidden text-xs leading-4 text-muted-foreground">
          {facts.map(({ key, icon: Icon, value, label }) =>
            Icon ? (
              <Tooltip key={key}>
                <TooltipTrigger asChild>
                  <span className="flex items-center gap-1 whitespace-nowrap">
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    <span className="tabular-nums" aria-hidden>
                      {value}
                    </span>
                    <span className="sr-only">{label}</span>
                  </span>
                </TooltipTrigger>
                <TooltipContent side="top">{label}</TooltipContent>
              </Tooltip>
            ) : (
              <span key={key} className="whitespace-nowrap">
                {value}
              </span>
            )
          )}
        </span>
      )}
    </div>
  );
}

interface OpenAPIConnectionCardProps {
  connection: OpenAPIConnection;
}

export function OpenAPIConnectionCard({
  connection,
}: OpenAPIConnectionCardProps) {
  const t = useTranslations("MCPServersPage.table");
  const tState = useTranslations("MCPServersPage.state");
  const toolCount = connection.available_tools.length;
  const connectionState = getOpenApiConnectionState(
    getOpenApiConnectionDisplayStatus(connection.status, toolCount),
    toolCount,
    connection.last_dispatch
  );

  return (
    <LinkedCard
      href={`/connections/openapi/${connection.id}`}
      title={connection.name}
      icon={<OpenAPIConnectionMark connection={connection} />}
      type="view"
      subtitle={
        <CardSubtitle
          status={
            <StatusIndicator size="sm" kind={connectionState.kind}>
              {tState(connectionState.key)}
            </StatusIndicator>
          }
          badge={
            <Badge
              size="sm"
              variant="outline"
              className="h-5 px-1.5 font-normal text-orange-600 border-orange-300"
            >
              OpenAPI
            </Badge>
          }
          facts={[
            {
              key: "tools",
              icon: ENTITY_ICONS.tool,
              value: String(toolCount),
              label: t("toolsTotal", { total: toolCount }),
            },
          ]}
        />
      }
    />
  );
}

/**
 * Identity mark for an OpenAPI connection: the favicon of the API it points
 * at, falling back to the domain initials when that host serves none.
 */
export function OpenAPIConnectionMark({
  connection,
  className,
}: {
  connection?: Pick<OpenAPIConnection, "base_url" | "name">;
  className?: string;
}) {
  return (
    <EntityMark
      identity={openApiIdentity(connection ?? {})}
      className={cn("h-6 w-6 shrink-0 rounded-md text-[9px]", className)}
    />
  );
}

export function MCPServerSpecCard({
  server,
  onConfigure,
}: MCPServerSpecCardProps) {
  const spec = server.json_spec as
    | {
        icons?: Array<{ src?: string }>;
        repository?: { url?: string; source?: string };
        title?: string;
      }
    | undefined;
  const specIcon = spec?.icons?.[0]?.src;
  const displayTitle = spec?.title || server.name;
  const repoUrl = spec?.repository?.url;
  const repoSource = spec?.repository?.source;

  return (
    <LinkedCard
      href={onConfigure ? undefined : `/connections/create/${server.id}`}
      onClick={onConfigure ? () => onConfigure(server) : undefined}
      title={displayTitle}
      icon={specIcon || getMCPIcon(server.name)}
      type="config"
      subtitle={
        <div className="flex flex-col gap-1.5">
          {server.description && (
            <span className="text-[11px] text-muted-foreground line-clamp-2 leading-tight">
              {server.description}
            </span>
          )}
          <div className="flex items-center gap-1 flex-wrap">
            {server.version && (
              <Badge
                size="sm"
                variant="secondary"
                className="h-5 px-1.5 font-normal"
              >
                v{server.version}
              </Badge>
            )}
            {getConnectionTypes(server).map((type) => (
              <Badge
                key={type}
                size="sm"
                variant="outline"
                className={`h-5 px-1.5 font-normal border text-[10px] ${CONNECTION_TYPE_CONFIG[type].color}`}
              >
                {CONNECTION_TYPE_CONFIG[type].label}
              </Badge>
            ))}
            {repoUrl && (
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
              >
                {repoSource === "github" ? (
                  <Github className="h-3 w-3" />
                ) : (
                  <Globe className="h-3 w-3" />
                )}
              </a>
            )}
          </div>
        </div>
      }
    />
  );
}

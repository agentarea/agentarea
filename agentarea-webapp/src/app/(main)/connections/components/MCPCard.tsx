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
} from "lucide-react";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getMcpVerificationStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import {
  CONNECTION_TYPE_CONFIG,
  getConnectionTypes,
  getEffectiveMCPVerificationStatus,
  getMCPConnectionIconSrc,
  getMCPConnectionTitle,
  getMCPInstanceToolCount,
} from "../utils";

interface MCPServerSpecCardProps {
  server: MCPServer;
  onConfigure?: (server: MCPServer) => void;
}

interface MCPInstanceCardProps {
  instance: MCPInstance;
  serverSpec?: MCPServer;
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
}: MCPInstanceCardProps) {
  const specType = (instance.json_spec?.type as string) || "docker";
  const toolCount = getMCPInstanceToolCount(instance);
  const vStatus = getEffectiveMCPVerificationStatus(instance);
  const statusPresentation = getMcpVerificationStatusPresentation(vStatus);

  const typeLabel =
    specType === "command"
      ? "Command"
      : specType === "url"
        ? "External"
        : specType === "bundle"
          ? "Bundle"
          : serverSpec?.name || "Docker";

  const providerIcon = getMCPConnectionIconSrc(instance, serverSpec);
  const displayTitle = getMCPConnectionTitle(instance, serverSpec);

  return (
    <LinkedCard
      href={`/connections/${instance.id}`}
      title={displayTitle}
      icon={providerIcon || getMCPIcon(instance.name)}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5 w-full">
          <StatusIndicator
            size="sm"
            tone={statusPresentation.tone}
            pulse={statusPresentation.pulse}
            className="shrink-0"
          >
            {statusPresentation.label}
          </StatusIndicator>
          <span className="truncate text-xs text-gray-500">{typeLabel}</span>
          {toolCount > 0 && (
            <span className="text-xs text-gray-400">· {toolCount} tools</span>
          )}
        </div>
      }
    />
  );
}

interface OpenAPIConnectionCardProps {
  connection: OpenAPIConnection;
}

export function OpenAPIConnectionCard({
  connection,
}: OpenAPIConnectionCardProps) {
  return (
    <LinkedCard
      href={`/connections/openapi/${connection.id}`}
      title={connection.name}
      icon={<OpenAPIConnectionMark connection={connection} />}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge
            size="sm"
            variant="outline"
            className="h-5 px-1.5 font-normal text-orange-600 border-orange-300"
          >
            OpenAPI
          </Badge>
          {connection.available_tools.length > 0 && (
            <span className="text-xs text-gray-500">
              {connection.available_tools.length} tools
            </span>
          )}
        </div>
      }
    />
  );
}

function getOpenAPIConnectionInitials(
  connection?: Pick<OpenAPIConnection, "base_url" | "name">
): string {
  if (!connection) return "API";

  try {
    const hostname = new URL(connection.base_url).hostname
      .replace(/^api\./, "")
      .replace(/^www\./, "");
    const labels = hostname.split(".").filter(Boolean);
    const domain = labels.length > 1 ? labels[labels.length - 2] : labels[0];
    return domain ? domain.slice(0, 2).toUpperCase() : "API";
  } catch {
    return connection.name.slice(0, 2).toUpperCase() || "API";
  }
}

export function OpenAPIConnectionMark({
  connection,
  className,
}: {
  connection?: Pick<OpenAPIConnection, "base_url" | "name">;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-[9px] font-semibold leading-none tracking-normal text-white dark:bg-zinc-100 dark:text-zinc-950",
        className
      )}
    >
      {getOpenAPIConnectionInitials(connection)}
    </span>
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

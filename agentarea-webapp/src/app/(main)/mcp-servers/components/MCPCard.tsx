import {
  Container,
  Server,
  Database,
  Folder,
  Github,
  Globe,
  MessageSquare,
  Cloud,
  Terminal,
  Cpu,
  Search,
  Mail,
  Command,
  Box,
  FileJson2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MCPServer, MCPInstance, OpenAPIConnection } from "../types";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { getConnectionTypes, CONNECTION_TYPE_CONFIG } from "../utils";

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
  if (lower.includes("postgres") || lower.includes("sql") || lower.includes("mongo") || lower.includes("redis")) return Database;
  if (lower.includes("file") || lower.includes("fs")) return Folder;
  if (lower.includes("git")) return Github;
  if (lower.includes("fetch") || lower.includes("http") || lower.includes("web") || lower.includes("browser")) return Globe;
  if (lower.includes("slack") || lower.includes("discord") || lower.includes("chat")) return MessageSquare;
  if (lower.includes("drive") || lower.includes("cloud") || lower.includes("aws") || lower.includes("s3")) return Cloud;
  if (lower.includes("docker") || lower.includes("kube")) return Container;
  if (lower.includes("terminal") || lower.includes("shell") || lower.includes("bash")) return Terminal;
  if (lower.includes("memory")) return Cpu;
  if (lower.includes("search") || lower.includes("brave") || lower.includes("google")) return Search;
  if (lower.includes("mail") || lower.includes("gmail") || lower.includes("outlook")) return Mail;
  if (lower.includes("linear") || lower.includes("jira") || lower.includes("project")) return Command;
  if (lower.includes("obsidian") || lower.includes("notion")) return Box;

  return Server;
}

export function MCPInstanceCard({
  instance,
  serverSpec,
}: MCPInstanceCardProps) {
  const specType = (instance.json_spec?.type as string) || "docker";
  const toolCount = (instance.json_spec?.available_tools as any[] | undefined)?.length ?? 0;
  const status = instance.status;

  const statusColor = {
    running: "text-green-600 border-green-300",
    connected: "text-blue-600 border-blue-300",
    stopped: "text-gray-500 border-gray-300",
    failed: "text-red-600 border-red-300",
    starting: "text-amber-600 border-amber-300",
    creating: "text-amber-600 border-amber-300",
    pending: "text-amber-600 border-amber-300",
  }[status] || "text-gray-500 border-gray-300";

  const statusLabel = {
    running: "Running",
    connected: "Connected",
    stopped: "Stopped",
    failed: "Failed",
    starting: "Starting",
    creating: "Creating",
    pending: "Pending",
  }[status] || status;

  const typeLabel = specType === "command" ? "Command" : specType === "url" ? "External" : specType === "bundle" ? "Bundle" : serverSpec?.name || "Docker";

  // Prefer icon from serverSpec json_spec, fall back to name-based Lucide icon
  const specIcon = (serverSpec as any)?.json_spec?.icons?.[0]?.src as string | undefined;
  const displayTitle = (serverSpec as any)?.json_spec?.title || instance.name;

  return (
    <LinkedCard
      href={`/mcp-servers/${instance.id}`}
      title={displayTitle}
      icon={specIcon || getMCPIcon(instance.name)}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5 w-full">
          <Badge size="sm" variant="outline" className={`h-5 px-1.5 font-normal ${statusColor}`}>
            {statusLabel}
          </Badge>
          <span className="truncate text-xs text-gray-500">
            {typeLabel}
          </span>
          {toolCount > 0 && (
            <span className="text-xs text-gray-400">
              · {toolCount} tools
            </span>
          )}
        </div>
      }
    />
  );
}

interface OpenAPIConnectionCardProps {
  connection: OpenAPIConnection;
}

export function OpenAPIConnectionCard({ connection }: OpenAPIConnectionCardProps) {
  return (
    <LinkedCard
      href={`/mcp-servers/openapi/${connection.id}`}
      title={connection.name}
      icon={FileJson2}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge size="sm" variant="outline" className="h-5 px-1.5 font-normal text-orange-600 border-orange-300">
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

export function MCPServerSpecCard({
  server,
  onConfigure,
}: MCPServerSpecCardProps) {
  const spec = (server as any).json_spec as Record<string, any> | undefined;
  const specIcon = spec?.icons?.[0]?.src as string | undefined;
  const displayTitle = spec?.title || server.name;
  const repoUrl = spec?.repository?.url as string | undefined;
  const repoSource = spec?.repository?.source as string | undefined;

  return (
    <LinkedCard
      href={onConfigure ? undefined : `/mcp-servers/create/${server.id}`}
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

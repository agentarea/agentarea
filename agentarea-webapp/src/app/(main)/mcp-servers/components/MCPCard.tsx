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
  Layers,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MCPServer, MCPInstance, OpenAPIConnection, CompoundMCP } from "../types";
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

  return (
    <LinkedCard
      href={`/mcp-servers/${instance.id}`}
      title={instance.name}
      icon={getMCPIcon(instance.name)}
      type="view"
      subtitle={
        <p className="truncate text-xs text-gray-500 w-full">
          {specType === "command" ? "Command" : specType === "url" ? "External" : serverSpec?.name || "Docker"}
        </p>
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

interface CompoundMCPCardProps {
  compound: CompoundMCP;
}

export function CompoundMCPCard({ compound }: CompoundMCPCardProps) {
  return (
    <LinkedCard
      href={`/mcp-servers/compound/${compound.id}`}
      title={compound.name}
      icon={Layers}
      type="view"
      subtitle={
        <div className="flex items-center gap-1.5">
          <Badge size="sm" variant="outline" className="h-5 px-1.5 font-normal text-violet-600 border-violet-300">
            Compound
          </Badge>
          <Badge size="sm" variant="outline" className="h-5 px-1.5 font-normal">
            {compound.routing_mode}
          </Badge>
        </div>
      }
    />
  );
}

export function MCPServerSpecCard({
  server,
  onConfigure,
}: MCPServerSpecCardProps) {
  return (
    <LinkedCard
      href={onConfigure ? undefined : `/mcp-servers/create/${server.id}`}
      onClick={onConfigure ? () => onConfigure(server) : undefined}
      title={server.name}
      icon={getMCPIcon(server.name)}
      type="config"
      subtitle={
        <div className="flex items-center gap-1">
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
        </div>
      }
    />
  );
}

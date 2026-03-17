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
  Box
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MCPServer, MCPInstance } from "../types";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

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
        <>
          {server.version && (
            <Badge
              size="sm"
              variant="secondary"
              className="h-5 px-1.5 font-normal"
            >
              v{server.version}
            </Badge>
          )}
          {server.docker_image_url && (
            <div title="Docker-based" className="flex items-center">
              <Container className="h-4 w-4 text-blue-500" />
            </div>
          )}
        </>
      }
    />
  );
}

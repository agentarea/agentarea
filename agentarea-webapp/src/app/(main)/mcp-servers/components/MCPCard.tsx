import Link from "next/link";
import { Server, Container, Terminal, Globe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { HoverLink } from "@/components/ui/hover-link";
import { MCPServer, MCPInstance } from "../types";

interface MCPServerSpecCardProps {
  server: MCPServer;
  onConfigure: (server: MCPServer) => void;
}

interface MCPInstanceCardProps {
  instance: MCPInstance;
  serverSpec?: MCPServer;
}

function InstanceTypeIcon({ type }: { type: string }) {
  switch (type) {
    case "command":
      return <Terminal className="h-4 w-4 text-orange-500" />;
    case "url":
      return <Globe className="h-4 w-4 text-blue-500" />;
    default:
      return <Container className="h-4 w-4 text-purple-500" />;
  }
}

export function MCPInstanceCard({
  instance,
  serverSpec,
}: MCPInstanceCardProps) {
  const specType = (instance.json_spec?.type as string) || "docker";

  return (
    <Link
      href={`/mcp-servers/${instance.id}`}
    >
      <Card className="group h-full flex flex-col justify-between px-4 py-4">
        <div className="mb-2 flex gap-2">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-slate-100 dark:bg-slate-800">
            <Server className="h-4 w-4 text-slate-600 dark:text-slate-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="truncate">{instance.name}</h4>
            <div className="flex items-center gap-1 mt-0.5">
              <InstanceTypeIcon type={specType} />
              <span className="text-xs text-gray-500">
                {specType === "command" ? "Command" : specType === "url" ? "External" : serverSpec?.name || "Docker"}
              </span>
            </div>
          </div>
        </div>
      <div className="flex justify-end -mb-2 -mt-1 -mr-2">
        <HoverLink text="View" />
      </div>
      </Card>
    </Link>
  );
}

export function MCPServerSpecCard({
  server,
  onConfigure,
}: MCPServerSpecCardProps) {
  return (
    <Card className="group h-full flex flex-col justify-between px-4 py-4 cursor-pointer" onClick={() => onConfigure(server)}>
      <div className="mb-2 flex gap-2">
        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-slate-100 dark:bg-slate-800">
          <Server className="h-4 w-4 text-slate-600 dark:text-slate-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="truncate">{server.name}</h4>
          <div className="flex items-center gap-1 mt-1">
            {server.version && (
              <Badge size="sm">
                v{server.version}
              </Badge>
            )}
            {server.docker_image_url && (
              <div title="Docker-based">
                <Container className="h-4 w-4 text-blue-500" />
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="flex justify-end -mb-2 -mt-1 -mr-2">
        <HoverLink text="Configure" />
      </div>
    </Card>
  );
}

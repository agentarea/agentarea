import Link from "next/link";
import { Server } from "lucide-react";
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

export function MCPInstanceCard({
  instance,
  serverSpec,
}: MCPInstanceCardProps) {
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
            {serverSpec && (
              <p className="truncate text-xs text-gray-500">
                {serverSpec.name}
              </p>
            )}
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
              <Badge variant="outline" className="text-xs">
                docker-based
              </Badge>
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

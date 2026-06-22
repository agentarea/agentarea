import Image from "next/image";
import Link from "next/link";
import { Edit, Pause, Play, Terminal, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getMcpCatalogStatusPresentation } from "@/lib/status";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

type MCPInstance = {
  id: string;
  name: string;
  status: string;
  server_id: string;
  created_at: string;
  updated_at: string;
  endpoint_url: string;
  config: { [key: string]: unknown };
  ip_address?: string;
  port?: number;
};

interface InstanceListProps {
  mcpInstanceList: MCPInstance[];
}

export function InstanceList({ mcpInstanceList }: InstanceListProps) {
  return (
    <>
      {mcpInstanceList && mcpInstanceList.length > 0 && (
        <div className="mb-2 mt-6 flex items-center space-x-2">
          <h2 className="flex items-center gap-2 text-xl font-semibold">
            <Image
              src="/mcp.svg"
              alt="MCP"
              width={20}
              height={20}
              className="text-current"
            />
            Server Instances
          </h2>
        </div>
      )}

      {mcpInstanceList && mcpInstanceList.length > 0 ? (
        <div className="">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Endpoint</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mcpInstanceList.map((instance) => {
                const isRunning = instance.status === "running";
                const statusPresentation = getMcpCatalogStatusPresentation(
                  instance.status
                );

                return (
                  <TableRow key={instance.id}>
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <Terminal className="h-4 w-4 text-primary" />
                        <span
                          className="max-w-[200px] truncate"
                          title={instance.name}
                        >
                          {instance.name}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusIndicator
                        tone={statusPresentation.tone}
                        pulse={statusPresentation.pulse}
                      >
                        {statusPresentation.label}
                      </StatusIndicator>
                    </TableCell>
                    <TableCell className="max-w-xs truncate">
                      {instance.endpoint_url || "N/A"}
                    </TableCell>
                    <TableCell>
                      {new Date(instance.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className={`h-8 w-8 p-0 ${isRunning ? "text-amber-600 hover:text-amber-700" : "text-green-600 hover:text-green-700"}`}
                        >
                          {isRunning ? (
                            <Pause className="h-4 w-4" />
                          ) : (
                            <Play className="h-4 w-4" />
                          )}
                          <span className="sr-only">
                            {isRunning ? "Pause" : "Start"}
                          </span>
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 w-8 p-0"
                          asChild
                        >
                          <Link href={`/mcp-servers/instances/${instance.id}`}>
                            <Edit className="h-4 w-4" />
                            <span className="sr-only">Edit</span>
                          </Link>
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 w-8 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                          <span className="sr-only">Remove</span>
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </>
  );
}

import { Button } from "@/components/ui/button";
import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { Globe, Server } from "lucide-react";
import Link from "next/link";
import { ServerList } from "@/components/mcp-servers/ServerList";
import { InstanceList } from "@/components/mcp-servers/InstanceList";

export default async function MCPServersPage() {
  const mcpServers = await listMCPServers();
  const mcpList = mcpServers.data || [];

  const mcpInstances = await listMCPServerInstances();
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <div className="p-6">
      <div className="flex flex-col space-y-4">
        <div className="flex justify-between items-center">
          <h1 className="text-2xl font-semibold">My MCP Servers</h1>
          <div className="flex space-x-2">
            <Button asChild className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white shadow-md transition-all duration-200">
              <Link href="/mcp-servers/add?type=self-hosted" className="flex items-center gap-1">
                <Server className="h-4 w-4" />
                Add Self-Hosted Server
              </Link>
            </Button>
            <Button asChild variant="outline" className="border-blue-600 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950 transition-all duration-200">
              <Link href="/mcp-servers/add?type=external" className="flex items-center gap-1">
                <Globe className="h-4 w-4" />
                Add External Server
              </Link>
            </Button>
            <Button asChild variant="secondary" className="border-blue-600 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950 transition-all duration-200">
              <Link href="/mcp-servers/setup" className="flex items-center gap-1">
                <Server className="h-4 w-4" />
                Setup MCP Instance
              </Link>
            </Button>
          </div>
        </div>
        
        <ServerList mcpList={mcpList} />
        <InstanceList mcpInstanceList={mcpInstanceList} />
      </div>
    </div>
  );
} 
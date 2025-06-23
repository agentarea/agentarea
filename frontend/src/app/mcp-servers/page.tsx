import { Button } from "@/components/ui/button";
import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { Globe, Server } from "lucide-react";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import ServerList from "@/components/mcp-servers/ServerList";
import { InstanceList } from "@/components/mcp-servers/InstanceList";

export default async function MCPServersPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined }
}) {
  const mcpServers = await listMCPServers();
  const mcpList = mcpServers.data || [];

  const mcpInstances = await listMCPServerInstances();
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <ContentBlock
      header={{
        title: "MCP Connections",
        controls: (
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
        )
      }}
    >
      <>
        <ServerList data={mcpList} searchParams={searchParams} />

        <InstanceList mcpInstanceList={mcpInstanceList} />
      </>
    </ContentBlock>
  );
} 
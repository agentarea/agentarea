import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { MCPSpecsSection } from "./components/MCPSpecsSection";
import { ActionCards } from "./components/ActionCards";
import { MyMCPsSection } from "./components/MyMCPsSection";
import ClientWrapper from "./ClientWrapper";
import ContentBlock from "@/components/ContentBlock";

export default async function MCPServersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const [mcpServers, mcpInstances, resolvedSearchParams] = await Promise.all([
    listMCPServers(),
    listMCPServerInstances(),
    searchParams,
  ]);

  const mcpList = mcpServers.data || [];
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <ContentBlock 
      header={{
        breadcrumb: [
          {label: "MCP Servers"},
        ],
        description: "Connect AI servers that provide tools, context, and capabilities to your agents",
        controls: (
          <div className="flex flex-col items-center lg:items-end gap-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <div className="h-1.5 w-1.5 bg-green-500 rounded-full animate-pulse"></div>
              {mcpInstanceList.length} Active Servers
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <div className="h-1.5 w-1.5 bg-blue-500 rounded-full"></div>
              {mcpList.length} Available Specs
            </div>
          </div>
        )
    }}>

<ClientWrapper>
      <>

        {/* Compact Quick Actions */}
        <div className="mb-6">
          <ActionCards />
        </div>

        {/* Compact My MCPs Section */}
        <div id="my-mcps" className="mb-6">
          <MyMCPsSection mcpInstances={mcpInstanceList} />
        </div>

        {/* Compact Browse MCP Specifications Section */}
        <div id="specs-section" className="mb-6">
          <MCPSpecsSection mcpServers={mcpList} searchParams={resolvedSearchParams} />
        </div>

        {/* Compact Footer */}
        <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
          <div className="text-center text-xs text-muted-foreground">
            <p>Need help setting up MCP servers? Check out our documentation or join the community.</p>
          </div>
        </div>
      </>
    </ClientWrapper>

    </ContentBlock>
  );
}
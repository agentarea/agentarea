import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { MCPSpecsSection } from "./components/MCPSpecsSection";
import { ActionCards } from "./components/ActionCards";
import { MyMCPsSection } from "./components/MyMCPsSection";
import ClientWrapper from "./ClientWrapper";

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
    <ClientWrapper>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Enhanced Header Section */}
        <div className="mb-12 text-center lg:text-left">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6">
            <div className="space-y-4">
              <div className="inline-flex items-center px-3 py-1 rounded-full bg-primary/10 text-primary text-sm font-medium">
                🚀 Model Context Protocol
              </div>
              <h1 className="text-4xl lg:text-5xl font-bold bg-gradient-to-r from-slate-900 to-slate-600 dark:from-white dark:to-slate-300 bg-clip-text text-transparent leading-tight">
                MCP Servers
              </h1>
              <p className="text-xl text-muted-foreground max-w-2xl leading-relaxed">
                Connect powerful AI servers that provide tools, context, and capabilities to supercharge your agents
              </p>
            </div>
            <div className="flex flex-col items-center lg:items-end gap-3">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-2 w-2 bg-green-500 rounded-full animate-pulse"></div>
                {mcpInstanceList.length} Active Servers
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-2 w-2 bg-blue-500 rounded-full"></div>
                {mcpList.length} Available Specs
              </div>
            </div>
          </div>
        </div>

        {/* Enhanced Quick Actions */}
        <div className="mb-12">
          <ActionCards />
        </div>

        {/* Enhanced My MCPs Section */}
        <div id="my-mcps" className="mb-12">
          <MyMCPsSection mcpInstances={mcpInstanceList} />
        </div>

        {/* Enhanced Browse MCP Specifications Section */}
        <div id="specs-section" className="mb-8">
          <MCPSpecsSection mcpServers={mcpList} searchParams={resolvedSearchParams} />
        </div>

        {/* Footer */}
        <div className="mt-16 pt-8 border-t border-slate-200 dark:border-slate-700">
          <div className="text-center text-sm text-muted-foreground">
            <p>Need help setting up MCP servers? Check out our documentation or join the community.</p>
          </div>
        </div>
      </div>
    </div>
    </ClientWrapper>
  );
}
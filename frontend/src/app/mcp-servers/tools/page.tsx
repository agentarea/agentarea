import { listMCPServerInstances } from "@/lib/api";
import { MyMCPsSection } from "../components/MyMCPsSection";
import ClientWrapper from "../ClientWrapper";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Plus, ArrowLeft } from "lucide-react";

export default async function MCPToolsPage() {
  const mcpInstances = await listMCPServerInstances();
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <ClientWrapper>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          {/* Header Section */}
          <div className="mb-6">
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
              <div className="space-y-2">
                <div className="inline-flex items-center px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium">
                  🔧 My MCP Tools
                </div>
                <h1 className="text-2xl lg:text-3xl font-bold bg-gradient-to-r from-slate-900 to-slate-600 dark:from-white dark:to-slate-300 bg-clip-text text-transparent leading-tight">
                  MCP Tools
                </h1>
                <p className="text-sm text-muted-foreground max-w-2xl">
                  Manage your configured MCP servers and monitor their status
                </p>
              </div>
              <div className="flex flex-col items-center lg:items-end gap-2">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <div className="h-1.5 w-1.5 bg-green-500 rounded-full animate-pulse"></div>
                  {mcpInstanceList.length} Active Tools
                </div>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <Link href="/mcp-servers/marketplace" className="flex items-center gap-2">
                      <Plus className="h-4 w-4" />
                      Browse Marketplace
                    </Link>
                  </Button>
                  <Button size="sm" asChild>
                    <Link href="/mcp-servers/add" className="flex items-center gap-2">
                      <Plus className="h-4 w-4" />
                      Add Custom Tool
                    </Link>
                  </Button>
                </div>
              </div>
            </div>
          </div>

          {/* My MCPs Section */}
          <div id="my-mcps" className="mb-6">
            <MyMCPsSection mcpInstances={mcpInstanceList} />
          </div>

          {/* Footer */}
          <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
            <div className="text-center text-xs text-muted-foreground">
              <p>Having issues with your MCP tools? Check the status indicators and configuration settings.</p>
            </div>
          </div>
        </div>
      </div>
    </ClientWrapper>
  );
}
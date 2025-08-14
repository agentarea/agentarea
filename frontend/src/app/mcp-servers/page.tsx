import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import ClientWrapper from "./ClientWrapper";
import ContentBlock from "@/components/ContentBlock";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { Store, Wrench, ArrowRight, Plus, Settings } from "lucide-react";

export default async function MCPServersPage() {
  const [mcpServers, mcpInstances] = await Promise.all([
    listMCPServers(),
    listMCPServerInstances(),
  ]);

  const mcpList = mcpServers.data || [];
  const mcpInstanceList = mcpInstances.data || [];

  return (
    <ClientWrapper>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-slate-100 dark:from-slate-900 dark:via-slate-800 dark:to-slate-900">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {/* Header Section */}
          <div className="mb-8 text-center">
            <div className="inline-flex items-center px-3 py-1 rounded-full bg-primary/10 text-primary text-sm font-medium mb-4">
              🚀 Model Context Protocol
            </div>
            <h1 className="text-3xl lg:text-4xl font-bold bg-gradient-to-r from-slate-900 to-slate-600 dark:from-white dark:to-slate-300 bg-clip-text text-transparent mb-4">
              MCP Connections
            </h1>
            <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
              Connect AI servers that provide tools, context, and capabilities to your agents
            </p>
          </div>

          {/* Navigation Cards */}
          <div className="grid md:grid-cols-2 gap-6 mb-8">
            {/* Marketplace Card */}
            <Card className="group hover:shadow-lg transition-all duration-200 border-2 hover:border-primary/20">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-900/30 group-hover:bg-blue-200 dark:group-hover:bg-blue-900/50 transition-colors">
                    <Store className="h-6 w-6 text-blue-600 dark:text-blue-400" />
                  </div>
                  <CardTitle className="text-xl">Marketplace</CardTitle>
                </div>
                <p className="text-muted-foreground">
                  Discover and install MCP providers from our curated marketplace
                </p>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="flex items-center justify-between mb-4">
                  <div className="text-sm text-muted-foreground">
                    {mcpList.length} available providers
                  </div>
                  <div className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400">
                    <div className="h-1.5 w-1.5 bg-blue-500 rounded-full"></div>
                    Updated daily
                  </div>
                </div>
                <Button asChild className="w-full group-hover:bg-primary/90 transition-colors">
                  <Link href="/mcp-servers/marketplace" className="flex items-center gap-2">
                    Browse Marketplace
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>

            {/* My Tools Card */}
            <Card className="group hover:shadow-lg transition-all duration-200 border-2 hover:border-primary/20">
              <CardHeader className="pb-4">
                <div className="flex items-center gap-3 mb-2">
                  <div className="p-2 rounded-lg bg-green-100 dark:bg-green-900/30 group-hover:bg-green-200 dark:group-hover:bg-green-900/50 transition-colors">
                    <Wrench className="h-6 w-6 text-green-600 dark:text-green-400" />
                  </div>
                  <CardTitle className="text-xl">My Tools</CardTitle>
                </div>
                <p className="text-muted-foreground">
                  Manage your configured MCP servers and monitor their status
                </p>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="flex items-center justify-between mb-4">
                  <div className="text-sm text-muted-foreground">
                    {mcpInstanceList.length} active tools
                  </div>
                  <div className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                    <div className="h-1.5 w-1.5 bg-green-500 rounded-full animate-pulse"></div>
                    Live status
                  </div>
                </div>
                <Button asChild variant="outline" className="w-full group-hover:bg-muted transition-colors">
                  <Link href="/mcp-servers/tools" className="flex items-center gap-2">
                    Manage Tools
                    <Settings className="h-4 w-4" />
                  </Link>
                </Button>
              </CardContent>
            </Card>
          </div>

          {/* Quick Actions */}
          <div className="text-center">
            <p className="text-sm text-muted-foreground mb-4">
              Need to add a custom MCP server?
            </p>
            <Button variant="outline" asChild>
              <Link href="/mcp-servers/add" className="flex items-center gap-2">
                <Plus className="h-4 w-4" />
                Add Custom Server
              </Link>
            </Button>
          </div>

          {/* Footer */}
          <div className="mt-12 pt-6 border-t border-slate-200 dark:border-slate-700">
            <div className="text-center text-sm text-muted-foreground">
              <p>Need help setting up MCP servers? Check out our documentation or join the community.</p>
            </div>
          </div>
        </div>
      </div>
    </ClientWrapper>

    </ContentBlock>
  );
}
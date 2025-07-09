import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { listMCPServers, listMCPServerInstances } from "@/lib/api";
import { CheckCircle, AlertCircle } from "lucide-react";
import Link from "next/link";
import { MCPSpecsSection } from "./components/MCPSpecsSection";
import { ActionCards } from "./components/ActionCards";
import { MyMCPsSection } from "./components/MyMCPsSection";

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
    <div className="p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold mb-2">🎯 MCP Setup</h1>
        <p className="text-muted-foreground">
          Set up and manage your Model Context Protocol (MCP) servers and instances
        </p>
      </div>

      {/* Quick Actions */}
      <ActionCards />

      {/* My MCPs Section */}
      <div id="my-mcps">
        <MyMCPsSection mcpInstances={mcpInstanceList} />
      </div>

      {/* Browse MCP Specifications Section */}
      <div id="specs-section">
        <MCPSpecsSection mcpServers={mcpList} searchParams={resolvedSearchParams} />
      </div>
    </div>
  );
} 
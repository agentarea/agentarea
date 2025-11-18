import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listMCPServerInstances, listMCPServers } from "@/lib/api";
import { MCPSpecsSection } from "./MCPSpecsSection";
import { MyMCPsSection } from "./MyMCPsSection";
import { MCPInstance, MCPServer } from "../types";

interface MCPServersContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function MCPServersContent({
  searchQuery = "",
  viewMode = "grid",
}: MCPServersContentProps) {
  const t = await getTranslations("MCPServersPage");

  // Fetch MCP servers and instances
  const [serversResponse, instancesResponse] = await Promise.all([
    listMCPServers(),
    listMCPServerInstances(),
  ]);

  // Handle API errors
  if (serversResponse.error || instancesResponse.error) {
    const errorMessage =
      (serversResponse.error as { detail?: Array<{ msg?: string }> })?.detail?.[0]
        ?.msg ||
      (instancesResponse.error as { detail?: Array<{ msg?: string }> })?.detail?.[0]
        ?.msg ||
      "Unknown error occurred";

    return (
      <div className="py-10 text-center">
        <p className="text-destructive">Error loading data: {errorMessage}</p>
      </div>
    );
  }

  const mcpServers = (serversResponse.data || []) as MCPServer[];
  const mcpInstances = (instancesResponse.data || []) as MCPInstance[];

  // Filter MCP instances based on search query
  const filteredInstances = searchQuery.trim()
    ? (() => {
        const query = searchQuery.toLowerCase();
        return mcpInstances.filter(
          (instance) =>
            instance.name?.toLowerCase().includes(query) ||
            instance.description?.toLowerCase().includes(query) ||
            instance.endpoint_url?.toLowerCase().includes(query)
        );
      })()
    : mcpInstances;

  // Filter MCP specs based on search query
  const filteredServers = searchQuery.trim()
    ? (() => {
        const query = searchQuery.toLowerCase();
        return mcpServers.filter(
          (server) =>
            server.name?.toLowerCase().includes(query) ||
            server.description?.toLowerCase().includes(query) ||
            (server.tags || []).some((tag) => tag.toLowerCase().includes(query))
        );
      })()
    : mcpServers;

  // Check for empty states (including user-created servers)
  const hasNoInstances = mcpInstances.length === 0;
  const hasNoServers = mcpServers.length === 0;
  const hasNoData = hasNoInstances && hasNoServers;
  const hasNoResults =
    filteredInstances.length === 0 &&
    filteredServers.length === 0 &&
    !hasNoData;

  // Handle global empty states
  if (hasNoData) {
    return (
      <EmptyState
        title="No MCP servers found"
        description="No MCP server instances or specifications are available"
        iconsType="mcp"
      />
    );
  }

  if (hasNoResults) {
    return (
      <EmptyState
        title="No matching servers"
        description={`No servers match your search query: "${searchQuery}"`}
        iconsType="mcp"
      />
    );
  }

  // Render both sections
  return (
    <div className="space-y-8">
      {/* My Active Servers Section */}
      <div id="my-mcps">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          My Active Servers ({filteredInstances.length})
        </h4>
        <MyMCPsSection
          mcpInstances={filteredInstances}
          mcpServers={mcpServers}
          viewMode={viewMode}
          searchQuery={searchQuery}
          hasNoData={hasNoInstances}
        />
      </div>

      {/* Browse MCP Specifications Section */}
      <div id="specs-section">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          Browse MCP Specifications ({filteredServers.length})
        </h4>
        <MCPSpecsSection
          mcpServers={filteredServers}
          searchParams={{ search: searchQuery }}
          viewMode={viewMode}
        />
      </div>
    </div>
  );
}

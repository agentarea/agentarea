import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { listMCPServerInstances, listMCPServers, listOpenAPIConnections } from "@/lib/api";
import { MCPSpecsSection } from "./MCPSpecsSection";
import { MyMCPsSection } from "./MyMCPsSection";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";

interface MCPServersContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function MCPServersContent({
  searchQuery = "",
  viewMode = "grid",
}: MCPServersContentProps) {
  const t = await getTranslations("MCPServersPage");

  // Fetch instances, servers, and OpenAPI connections in parallel
  const [instancesResponse, serversResponse, openApiResponse] = await Promise.all([
    listMCPServerInstances(),
    listMCPServers({ page_size: 100 }),
    listOpenAPIConnections(),
  ]);

  if (instancesResponse.error) {
    const errorMessage =
      (instancesResponse.error as { detail?: Array<{ msg?: string }> })?.detail?.[0]
        ?.msg || "Unknown error occurred";

    return (
      <div className="py-10 text-center">
        <p className="text-destructive">Error loading data: {errorMessage}</p>
      </div>
    );
  }

  const mcpInstances = (instancesResponse.data || []) as MCPInstance[];
  const serversData = serversResponse.data as any;
  const mcpServers = (serversData?.items || serversData || []) as MCPServer[];
  const openApiConnections = (openApiResponse.data || []) as OpenAPIConnection[];

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

  // Filter OpenAPI connections based on search query
  const filteredOpenApi = searchQuery.trim()
    ? (() => {
        const query = searchQuery.toLowerCase();
        return openApiConnections.filter(
          (conn) =>
            conn.name?.toLowerCase().includes(query) ||
            conn.description?.toLowerCase().includes(query) ||
            conn.base_url?.toLowerCase().includes(query)
        );
      })()
    : openApiConnections;

  const totalConnections = filteredInstances.length + filteredOpenApi.length;

  // Render both sections
  return (
    <div className="space-y-8">
      {/* My Connections Section — MCP instances + OpenAPI connections */}
      <div id="my-connections">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("myConnections")} ({totalConnections})
        </h4>
        <MyMCPsSection
          mcpInstances={filteredInstances}
          mcpServers={mcpServers}
          openApiConnections={filteredOpenApi}
          viewMode={viewMode}
          searchQuery={searchQuery}
          hasNoData={mcpInstances.length === 0 && openApiConnections.length === 0}
        />
      </div>

      {/* Browse MCP Specifications Section — client-side with infinite scroll */}
      <div id="specs-section">
        <MCPSpecsSection
          searchParams={{ search: searchQuery }}
          viewMode={viewMode}
        />
      </div>
    </div>
  );
}

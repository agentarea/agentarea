import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { formatApiError } from "@/lib/api-errors";
import {
  listAgents,
  listMCPServerInstances,
  listMCPServerSpecs,
  listOpenAPIConnections,
} from "@/lib/api";
import MCPSkeleton, { mcpSkeletonColumns } from "./MCPSkeleton";
import { MyMCPsSection } from "./MyMCPsSection";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import { buildConnectionUsage } from "../usage";

interface MCPServersContentProps {
  searchQuery?: string;
  viewMode?: string;
}

export default async function MCPServersContent({
  searchQuery = "",
  viewMode = "grid",
}: MCPServersContentProps) {
  const t = await getTranslations("MCPServersPage");

  // Only your configured connections live here — discovery is in Explore.
  return (
    <div id="my-connections">
      <Suspense
        fallback={
          <MCPSkeleton
            viewMode={viewMode}
            columns={mcpSkeletonColumns(t)}
            headerLabel={t("myConnections")}
          />
        }
      >
        <MyConnectionsSectionServer searchQuery={searchQuery} viewMode={viewMode} />
      </Suspense>
    </div>
  );
}

async function MyConnectionsSectionServer({
  searchQuery,
  viewMode,
}: {
  searchQuery: string;
  viewMode: string;
}) {
  const t = await getTranslations("MCPServersPage");

  // Instances, OpenAPI connections and agents in parallel. Agents are fetched
  // once and inverted locally into per-connection usage — the per-instance
  // consumers endpoint scans every agent, so calling it per row would be a
  // full scan per connection.
  const [instancesResponse, openApiResponse, agentsResponse] = await Promise.all([
    listMCPServerInstances(),
    listOpenAPIConnections(),
    listAgents(),
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

  if (openApiResponse.error) {
    console.error("Failed to load OpenAPI connections:", openApiResponse.error);
  }

  const mcpInstances = (instancesResponse.data || []) as MCPInstance[];

  // Exactly the specs these instances use: the paged spec list would leave out
  // any whose spec is not on its first page, and with it their icon.
  const specsResponse = await listMCPServerSpecs(
    mcpInstances.map((instance) => instance.server_spec_id)
  );
  if (specsResponse.error) {
    return (
      <div className="py-10 text-center">
        <p className="text-destructive">
          Error loading data: {formatApiError(specsResponse.error)}
        </p>
      </div>
    );
  }
  const mcpServers = (specsResponse.data ?? []) as MCPServer[];
  const openApiConnections = (openApiResponse.data || []) as OpenAPIConnection[];
  const usage = buildConnectionUsage(
    agentsResponse.error ? [] : (agentsResponse.data ?? []),
    mcpInstances.map((instance) => ({ id: instance.id, name: instance.name }))
  );

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

  if (searchQuery.trim() && totalConnections === 0) {
    return (
      <div className="py-1">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("myConnections")} (0)
        </h4>
        <EmptyState
          title="No matching connections"
          description={`No connections match your search query: "${searchQuery}"`}
          iconsType="mcp"
          action={{ label: "Clear search", href: "/connections" }}
        />
      </div>
    );
  }

  return (
    <>
      <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
        {t("myConnections")} ({totalConnections})
      </h4>
      <MyMCPsSection
        mcpInstances={filteredInstances}
        mcpServers={mcpServers}
        openApiConnections={filteredOpenApi}
        usage={usage}
        viewMode={viewMode}
        searchQuery={searchQuery}
        hasNoData={mcpInstances.length === 0 && openApiConnections.length === 0}
      />
    </>
  );
}

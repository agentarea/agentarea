import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import SectionLoadError from "@/components/SectionLoadError";
import { apiErrorMessage } from "@/lib/api-errors";
import type { ListFilter } from "../list-sections";
import { MCPServer } from "../types";
import { getConnectionsFrom } from "./connectionsData";
import MCPSkeleton, { mcpSkeletonColumns } from "./MCPSkeleton";
import { MyMCPsSection } from "./MyMCPsSection";

interface MCPServersContentProps {
  searchQuery?: string;
  viewMode?: string;
  filter?: ListFilter;
  /** A catalog item id: only the connections made from it. */
  source?: string | null;
}

export default async function MCPServersContent({
  searchQuery = "",
  viewMode = "grid",
  filter = "all",
  source = null,
}: MCPServersContentProps) {
  const t = await getTranslations("MCPServersPage");

  // Only your configured connections live here — discovery is in Explore.
  return (
    <div id="my-connections">
      <Suspense
        fallback={
          <MCPSkeleton viewMode={viewMode} columns={mcpSkeletonColumns(t)} />
        }
      >
        <MyConnectionsSectionServer
          searchQuery={searchQuery}
          viewMode={viewMode}
          filter={filter}
          source={source}
        />
      </Suspense>
    </div>
  );
}

async function MyConnectionsSectionServer({
  searchQuery,
  viewMode,
  filter,
  source,
}: {
  searchQuery: string;
  viewMode: string;
  filter: ListFilter;
  source: string | null;
}) {
  const t = await getTranslations("MCPServersPage");

  const {
    instancesResponse,
    openApiResponse,
    agentsResponse,
    specsResponse,
    instances: mcpInstances,
    openApiConnections,
    usage,
  } = await getConnectionsFrom(source);

  if (instancesResponse.error) {
    return (
      <RetryEmptyState
        title={t("loadErrors.title")}
        description={apiErrorMessage(
          instancesResponse,
          t("loadErrors.instances")
        )}
        iconsType="mcp"
      />
    );
  }

  // A failed part is reported where the list starts, never rendered as a
  // shorter list or as "unused" connections.
  const openApiError = openApiResponse.error
    ? apiErrorMessage(openApiResponse, t("loadErrors.openapi"))
    : null;
  const usageError =
    agentsResponse.error || !agentsResponse.data
      ? apiErrorMessage(agentsResponse, t("loadErrors.usage"))
      : null;

  if (specsResponse?.error) {
    return (
      <RetryEmptyState
        title={t("loadErrors.title")}
        description={apiErrorMessage(specsResponse, t("loadErrors.servers"))}
        iconsType="mcp"
      />
    );
  }
  const mcpServers = (specsResponse?.data ?? []) as MCPServer[];
  const loadErrors = (
    <>
      {openApiError && <SectionLoadError message={openApiError} />}
      {usageError && <SectionLoadError message={usageError} />}
    </>
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

  if (openApiError && mcpInstances.length === 0) {
    return loadErrors;
  }

  if (searchQuery.trim() && totalConnections === 0) {
    return (
      <div className="py-1">
        {loadErrors}
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
      {loadErrors}
      <MyMCPsSection
        mcpInstances={filteredInstances}
        mcpServers={mcpServers}
        openApiConnections={filteredOpenApi}
        usage={usage}
        viewMode={viewMode}
        filter={filter}
        searchQuery={searchQuery}
        hasNoData={mcpInstances.length === 0 && openApiConnections.length === 0}
      />
    </>
  );
}

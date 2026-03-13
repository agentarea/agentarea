import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
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

  const serversResponse = await listMCPServers();
  if (serversResponse.error) {
    const errorMessage =
      (serversResponse.error as { detail?: Array<{ msg?: string }> })?.detail?.[0]
        ?.msg || "Unknown error occurred";

    return (
      <div className="py-10 text-center">
        <p className="text-destructive">Error loading data: {errorMessage}</p>
      </div>
    );
  }

  const mcpServers = (serversResponse.data || []) as MCPServer[];

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

  // Render both sections
  return (
    <div className="space-y-8">
      {/* My Active Servers Section */}
      <div id="my-mcps">
        <Suspense
          fallback={
            <div className="py-1">
              <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
                {t("myActiveServers")}
              </h4>
              <div className="flex h-32 items-center justify-center">
                <LoadingSpinner />
              </div>
            </div>
          }
        >
          <MyMCPsSectionServer
            searchQuery={searchQuery}
            viewMode={viewMode}
            mcpServers={mcpServers}
          />
        </Suspense>
      </div>

      {/* Browse MCP Specifications Section */}
      <div id="specs-section">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("browseSpecifications")} ({filteredServers.length})
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

async function MyMCPsSectionServer({
  searchQuery,
  viewMode,
  mcpServers,
}: {
  searchQuery: string;
  viewMode: string;
  mcpServers: MCPServer[];
}) {
  const t = await getTranslations("MCPServersPage");
  const instancesResponse = await listMCPServerInstances();

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

  if (searchQuery.trim() && filteredInstances.length === 0) {
    return (
      <div className="py-1">
        <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
          {t("myActiveServers")} (0)
        </h4>
        <EmptyState
          title="No matching instances"
          description={`No instances match your search query: "${searchQuery}"`}
          iconsType="mcp"
        />
      </div>
    );
  }

  return (
    <>
      <h4 className="mb-3 text-xs uppercase text-muted-foreground/80">
        {t("myActiveServers")} ({filteredInstances.length})
      </h4>
      <MyMCPsSection
        mcpInstances={filteredInstances}
        mcpServers={mcpServers}
        viewMode={viewMode}
        searchQuery={searchQuery}
        hasNoData={mcpInstances.length === 0}
      />
    </>
  );
}

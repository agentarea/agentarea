import { cache } from "react";
import {
  listAgents,
  listMCPServerInstances,
  listMCPServerSpecs,
  listOpenAPIConnections,
} from "@/lib/api";
import type { MCPInstance, OpenAPIConnection } from "../types";
import { buildConnectionUsage, type ConnectionUsage } from "../usage";

/**
 * Request-memoized connections fetch. Both the filter counts in the toolbar
 * and the listing read through this, so the lists are fetched once per
 * request (React `cache` dedupes within a single render).
 */
export const getConnectionsCached = cache(async () => {
  // Instances, OpenAPI connections and agents in parallel. Agents are fetched
  // once and inverted locally into per-connection usage — the per-instance
  // consumers endpoint scans every agent, so calling it per row would be a
  // full scan per connection.
  const [instancesResponse, openApiResponse, agentsResponse] =
    await Promise.all([
      listMCPServerInstances(),
      listOpenAPIConnections(),
      listAgents(),
    ]);

  const instances = (instancesResponse.data || []) as MCPInstance[];

  // Exactly the specs these instances use: the paged spec list would leave out
  // any whose spec is not on its first page, and with it their icon.
  const specsResponse = instancesResponse.error
    ? null
    : await listMCPServerSpecs(
        instances.map((instance) => instance.server_spec_id)
      );

  // Without the agents there is no usage to show: no row may read "unused".
  const usage: Record<string, ConnectionUsage> =
    agentsResponse.error || !agentsResponse.data
      ? {}
      : buildConnectionUsage(
          agentsResponse.data,
          instances.map((instance) => ({
            id: instance.id,
            name: instance.name,
          }))
        );

  return {
    instancesResponse,
    openApiResponse,
    agentsResponse,
    specsResponse,
    instances,
    openApiConnections: (openApiResponse.data || []) as OpenAPIConnection[],
    usage,
  };
});

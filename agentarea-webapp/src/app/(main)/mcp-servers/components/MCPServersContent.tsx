import {
  listMCPServerInstances,
  listMCPServers,
  listOpenAPIConnections,
} from "@/lib/api";
import { MCPInstance, MCPServer, OpenAPIConnection } from "../types";
import MCPConnectionsView, {
  type MCPConnectionsInitialState,
} from "./MCPConnectionsView";

interface MCPServersContentProps {
  initial: MCPConnectionsInitialState;
}

export default async function MCPServersContent({
  initial,
}: MCPServersContentProps) {
  const [serversResponse, instancesResponse, openApiResponse] =
    await Promise.all([
      listMCPServers({ page_size: 100 }),
      listMCPServerInstances(),
      listOpenAPIConnections(),
    ]);

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

  const serversData = serversResponse.data as
    | { items?: MCPServer[] }
    | MCPServer[]
    | null;
  const mcpServers = (
    Array.isArray(serversData) ? serversData : serversData?.items || []
  ) as MCPServer[];

  if (openApiResponse.error) {
    console.error("Failed to load OpenAPI connections:", openApiResponse.error);
  }

  const mcpInstances = (instancesResponse.data || []) as MCPInstance[];
  const openApiConnections = (openApiResponse.data || []) as OpenAPIConnection[];

  return (
    <MCPConnectionsView
      mcpInstances={mcpInstances}
      mcpServers={mcpServers}
      openApiConnections={openApiConnections}
      initial={initial}
    />
  );
}

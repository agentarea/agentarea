import { getBuiltinToolLabel } from "@/app/w/[workspace]/(main)/agents/create/utils/builtinToolUtils";
import { getOpenApiConnectionInitials } from "@/lib/entity-identity";
import {
  McpInstance,
  McpServer,
  resolveMcpRef,
} from "@/lib/mcp/resolveMcpRef";
import { Agent } from "@/types";

/** The fields of an OpenAPI connection needed to identify it in the UI. */
export type OpenApiConnectionRef = {
  id: string;
  name: string;
  base_url: string;
};

/**
 * Render-ready descriptor for one of an agent's tools.
 *
 * MCP icons are resolved from the live registry (see {@link resolveMcpRef});
 * OpenAPI tools resolve to a workspace connection and carry its domain initials
 * (those connections have no logo to show); builtin toolsets map to a lucide
 * icon by namespace. A ref that resolves to nothing is marked `resolved: false`
 * so the UI can show it as "not connected" instead of faking an identity.
 */
export type AgentToolIcon =
  | { kind: "builtin"; toolName: string; label: string }
  | { kind: "mcp"; src?: string; label: string; resolved: boolean }
  | { kind: "openapi"; initials?: string; label: string; resolved: boolean }
  | { kind: "agent"; label: string };

/** Workspace lookups an agent's tool refs are resolved against. */
export interface AgentToolRegistry {
  mcpInstances?: readonly McpInstance[];
  mcpServers?: readonly McpServer[];
  openApiConnections?: readonly OpenApiConnectionRef[];
}

/**
 * Resolve an agent's `tools` array into render-ready icon descriptors. Pass the
 * workspace MCP instances, server specs and OpenAPI connections so refs resolve
 * to the real connected services.
 */
export function resolveAgentToolIcons(
  agent: Agent,
  registry: AgentToolRegistry = {}
): AgentToolIcon[] {
  const {
    mcpInstances = [],
    mcpServers = [],
    openApiConnections = [],
  } = registry;
  const tools = Array.isArray(agent.tools) ? agent.tools : [];
  const icons: AgentToolIcon[] = [];

  for (const tool of tools) {
    if (!tool || typeof tool.name !== "string") continue;

    if (tool.type === "code") {
      icons.push({
        kind: "builtin",
        toolName: tool.name,
        label: getBuiltinToolLabel(tool.name),
      });
    } else if (tool.type === "mcp") {
      const res = resolveMcpRef(tool.name, mcpInstances, mcpServers);
      icons.push({
        kind: "mcp",
        src: res.status === "unresolved" ? undefined : res.iconSrc,
        label: res.displayName,
        resolved: res.status !== "unresolved",
      });
    } else if (tool.type === "openapi") {
      // Agents reference a connection by id (webapp flow) or by name (bundle
      // installs) — mirror both, the same way MCP refs are resolved.
      const connectionId = tool.settings?.openapi_connection_id;
      const lower = tool.name.toLowerCase();
      const connection =
        (connectionId
          ? openApiConnections.find((c) => c.id === connectionId)
          : undefined) ??
        openApiConnections.find((c) => c.name?.toLowerCase() === lower);
      icons.push({
        kind: "openapi",
        label: connection?.name ?? tool.name,
        initials: connection
          ? getOpenApiConnectionInitials(connection)
          : undefined,
        resolved: Boolean(connection),
      });
    } else if (tool.type === "agent") {
      icons.push({ kind: "agent", label: tool.name });
    }
  }

  return icons;
}

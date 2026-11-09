import type { McpServerInstanceResponse, McpServerResponse } from "@/api/client/types.gen";
import {
  getMCPConnectionIconSrc,
  mcpIdentity,
  type EntityIdentity,
} from "@/lib/entity-identity";

/**
 * Resolves an agent's MCP tool reference to a concrete instance/server.
 *
 * An agent stores MCP tools as `{ type: "mcp", name: <ref> }`. The runtime reaches
 * a connection by its instance UUID only (`ToolManager._discover_instance_tools`):
 * connection names are not unique, so a name is bound to an id when the agent is
 * saved, and only while exactly one connection carries it. A ref that is still a
 * name reaches no connection, so it never resolves to an instance here. It may
 * name a server spec (a catalog agent's MCP not connected yet), shown as
 * `status: "server"`; otherwise it is `status: "unresolved"`.
 */

export type McpInstance = McpServerInstanceResponse;
export type McpServer = McpServerResponse;

export interface McpAvailableTool {
  name: string;
  display_name?: string;
  description?: string;
  inputSchema?: unknown;
}

export type McpRefResolution =
  | {
      status: "instance";
      ref: string;
      instance: McpInstance;
      server?: McpServer;
      displayName: string;
      iconSrc?: string;
      availableTools: McpAvailableTool[];
    }
  | {
      status: "server";
      ref: string;
      server: McpServer;
      displayName: string;
      iconSrc?: string;
      availableTools: McpAvailableTool[];
    }
  | { status: "unresolved"; ref: string; displayName: string };

function toAvailableTools(raw: unknown): McpAvailableTool[] {
  if (!Array.isArray(raw)) return [];
  const tools: McpAvailableTool[] = [];
  for (const item of raw) {
    if (
      item &&
      typeof item === "object" &&
      typeof (item as { name?: unknown }).name === "string"
    ) {
      const t = item as {
        name: string;
        display_name?: unknown;
        description?: unknown;
        inputSchema?: unknown;
        input_schema?: unknown;
      };
      tools.push({
        name: t.name,
        display_name:
          typeof t.display_name === "string" ? t.display_name : undefined,
        description:
          typeof t.description === "string" ? t.description : undefined,
        inputSchema: t.inputSchema ?? t.input_schema,
      });
    }
  }
  return tools;
}

function instanceTools(instance: McpInstance): McpAvailableTool[] {
  const top = toAvailableTools(instance.tools);
  if (top.length) return top;
  const spec = instance.json_spec as Record<string, unknown> | null | undefined;
  return toAvailableTools(spec?.available_tools);
}

export function resolveMcpRef(
  ref: string,
  instances: readonly McpInstance[],
  servers: readonly McpServer[]
): McpRefResolution {
  const lower = ref.toLowerCase();

  const instance = instances.find((i) => i.id === ref);

  if (instance) {
    const server = instance.server_spec_id
      ? servers.find((s) => s.id === instance.server_spec_id)
      : undefined;
    return {
      status: "instance",
      ref,
      instance,
      server,
      displayName: instance.name || ref,
      iconSrc: getMCPConnectionIconSrc(instance, server),
      availableTools: instanceTools(instance),
    };
  }

  const server =
    servers.find((s) => s.id === ref) ??
    servers.find((s) => s.name?.toLowerCase() === lower);

  if (server) {
    return {
      status: "server",
      ref,
      server,
      displayName: server.name || ref,
      iconSrc: getMCPConnectionIconSrc(server),
      availableTools: [],
    };
  }

  return { status: "unresolved", ref, displayName: ref };
}

/** The `EntityMark` identity of an MCP ref, resolved the same way as `resolveMcpRef`. */
export function mcpRefIdentity(
  ref: string,
  instances: readonly McpInstance[],
  servers: readonly McpServer[]
): EntityIdentity {
  const resolved = resolveMcpRef(ref, instances, servers);
  if (resolved.status === "instance") {
    return mcpIdentity(resolved.instance, resolved.server);
  }
  if (resolved.status === "server") return mcpIdentity(resolved.server);
  return mcpIdentity({});
}

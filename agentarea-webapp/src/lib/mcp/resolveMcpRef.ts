import type { components } from "@/api/schema";
import { getMCPConnectionIconSrc } from "@/app/(main)/connections/utils";

/**
 * Resolves an agent's MCP tool reference to a concrete instance/server.
 *
 * An agent stores MCP tools as `{ type: "mcp", name: <ref> }`. The `<ref>` is
 * either an instance UUID (webapp create/edit flow) or an instance NAME (bundle
 * installs). The Temporal runtime resolves both — `get(UUID(ref)) ?? get_by_name(ref)`
 * in `agent_execution_activities.py` — so this is the single source of truth the
 * UI mirrors. A ref that matches neither is genuinely dangling (the runtime skips
 * it), surfaced here as `status: "unresolved"` rather than a misleading icon.
 */

export type McpInstance = components["schemas"]["MCPServerInstanceResponse"];
export type McpServer = components["schemas"]["MCPServerResponse"];

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

  const instance =
    instances.find((i) => i.id === ref) ??
    instances.find((i) => i.name?.toLowerCase() === lower);

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

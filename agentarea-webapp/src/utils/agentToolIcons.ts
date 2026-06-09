import {
  McpInstance,
  McpServer,
  resolveMcpRef,
} from "@/lib/mcp/resolveMcpRef";
import { Agent } from "@/types";

/**
 * Render-ready descriptor for one of an agent's tools.
 *
 * MCP/OpenAPI icons are resolved from the live registry (see {@link resolveMcpRef}),
 * builtin tools map to a lucide icon by name. An MCP ref that resolves to no
 * instance/server is marked `resolved: false` so the UI can show it as "not
 * connected" instead of faking an icon.
 */
export type AgentToolIcon =
  | { kind: "builtin"; toolName: string; label: string }
  | { kind: "mcp"; src?: string; label: string; resolved: boolean }
  | { kind: "openapi"; src?: string; label: string };

/**
 * Resolve an agent's `tools` array into render-ready icon descriptors. Pass the
 * workspace MCP instances and server specs so MCP refs resolve to real icons.
 */
export function resolveAgentToolIcons(
  agent: Agent,
  mcpInstances: readonly McpInstance[] = [],
  mcpServers: readonly McpServer[] = []
): AgentToolIcon[] {
  const tools = Array.isArray(agent.tools) ? agent.tools : [];
  const icons: AgentToolIcon[] = [];

  for (const tool of tools) {
    if (!tool || typeof tool.name !== "string") continue;

    if (tool.type === "code") {
      icons.push({ kind: "builtin", toolName: tool.name, label: tool.name });
    } else if (tool.type === "mcp") {
      const res = resolveMcpRef(tool.name, mcpInstances, mcpServers);
      icons.push({
        kind: "mcp",
        src: res.status === "unresolved" ? undefined : res.iconSrc,
        label: res.displayName,
        resolved: res.status !== "unresolved",
      });
    } else if (tool.type === "openapi") {
      icons.push({ kind: "openapi", label: tool.name });
    }
  }

  return icons;
}

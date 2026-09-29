import type { AgentResponse } from "@/api/client/types.gen";

/**
 * How a connection is actually used by the workspace's agents, derived from the
 * agents' own tool configs. Mirrors the reverse lookup the
 * `/mcp-server-instances/{id}/consumers` endpoint performs per instance —
 * computed here from one `listAgents()` call so the list page does not issue
 * one full agent scan per row.
 */
export interface ConnectionUsage {
  /** Agents that attach this connection. */
  agents: number;
  /** Distinct tools granted across those agents; `null` when at least one agent is granted every tool. */
  grantedTools: number | null;
}

/**
 * A raw agent tool-config references an MCP connection by instance UUID or by
 * instance name — the same rule the backend applies in `_mcp_config_matches`.
 */
export function buildConnectionUsage(
  agents: AgentResponse[],
  connectionKeys: { id: string; name: string }[]
): Record<string, ConnectionUsage> {
  const keyById = new Map<string, string>();
  for (const connection of connectionKeys) {
    keyById.set(connection.id, connection.id);
    if (connection.name) keyById.set(connection.name, connection.id);
  }

  const grantedByConnection = new Map<string, Set<string>>();
  const agentsByConnection = new Map<string, number>();
  const wildcardConnections = new Set<string>();

  for (const agent of agents) {
    // One agent may list the same connection once; count it once per config.
    const seen = new Set<string>();
    for (const toolConfig of agent.tools ?? []) {
      if (toolConfig.type !== "mcp") continue;
      const connectionId = keyById.get(toolConfig.name);
      if (!connectionId || seen.has(connectionId)) continue;
      seen.add(connectionId);
      agentsByConnection.set(
        connectionId,
        (agentsByConnection.get(connectionId) ?? 0) + 1
      );

      const allowed = toolConfig.settings?.allowed_tools;
      if (allowed == null) {
        wildcardConnections.add(connectionId);
        continue;
      }
      const granted =
        grantedByConnection.get(connectionId) ?? new Set<string>();
      for (const permission of allowed) granted.add(permission.tool_name);
      grantedByConnection.set(connectionId, granted);
    }
  }

  const usage: Record<string, ConnectionUsage> = {};
  for (const connection of connectionKeys) {
    usage[connection.id] = {
      agents: agentsByConnection.get(connection.id) ?? 0,
      grantedTools: wildcardConnections.has(connection.id)
        ? null
        : (grantedByConnection.get(connection.id)?.size ?? 0),
    };
  }
  return usage;
}

export interface LastDispatch {
  status: string;
  at: string | null;
  error: string | null;
}

/**
 * The connection's last tool call, written by the execution activity on every
 * dispatch. Absent means no agent has called this connection yet — which is a
 * different fact from a failed verification.
 */
export function readLastDispatch(value: unknown): LastDispatch | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const status = typeof record.status === "string" ? record.status : null;
  if (!status) return null;
  const rawError = record.error;
  return {
    status,
    at: typeof record.at === "string" ? record.at : null,
    error:
      typeof rawError === "string"
        ? rawError
        : rawError && typeof rawError === "object"
          ? ((rawError as { message?: unknown }).message as string) || null
          : null,
  };
}

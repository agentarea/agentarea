// MCP Apps host calls, spoken as MCP to the governed per-connection proxy
// (/v1/mcp/{instance_id}/mcp). The proxy owns access control, governance on
// tools/call, and credential injection; nothing here re-implements them.

import "server-only";
import { setTimeout as delay } from "node:timers/promises";
import {
  Client,
  StreamableHTTPClientTransport,
  type CallToolResult,
} from "@modelcontextprotocol/client";
import { env } from "@/env";
import { MCP_APP_TIMEOUT_MS } from "@/lib/server-timeouts";
import { workspaceFetch } from "@/lib/workspace-request";
import { uiResourceFromReadResult, type McpAppUiResource } from "./tools";

const HOST_CLIENT_INFO = {
  name: "AgentArea MCP Apps host",
  version: "0.1.0",
} as const;
// Set by the manager's demand gateway (mcpgateway.StartingHeader) on its own
// "workload is starting" 503; the proxy passes it through.
const GATEWAY_STARTING_HEADER = "x-agentarea-mcp-starting";
// Closing the session is best effort and must still run after the deadline.
const SESSION_CLOSE_TIMEOUT_MS = 5_000;

/**
 * Fetch for the proxy, bounded by `deadline`.
 *
 * While one request cold-starts a reclaimed workload, the manager's demand
 * gateway answers concurrent requests 503 and marks them as never forwarded,
 * so repeating them cannot run a tool twice. Any other 503, from the workload
 * or a remote server, is returned as is.
 */
function proxyFetch(deadline: AbortSignal) {
  return async (url: string | URL, init: RequestInit = {}) => {
    const bound =
      init.method === "DELETE"
        ? AbortSignal.timeout(SESSION_CLOSE_TIMEOUT_MS)
        : deadline;
    const signal = init.signal ? AbortSignal.any([init.signal, bound]) : bound;
    for (;;) {
      const response = await workspaceFetch(String(url), { ...init, signal });
      if (
        response.status !== 503 ||
        response.headers.get(GATEWAY_STARTING_HEADER) !== "1"
      ) {
        return response;
      }
      await response.body?.cancel();
      const retryAfterSeconds = Number(response.headers.get("retry-after"));
      await delay(Math.max(1, retryAfterSeconds || 1) * 1000, undefined, {
        signal,
      });
    }
  };
}

async function withProxyClient<T>(
  instanceId: string,
  operation: (
    client: Client,
    bounds: { timeout: number; signal: AbortSignal }
  ) => Promise<T>
): Promise<T> {
  const deadline = AbortSignal.timeout(MCP_APP_TIMEOUT_MS);
  const transport = new StreamableHTTPClientTransport(
    new URL(
      `${env.API_URL.replace(/\/+$/, "")}/v1/mcp/${encodeURIComponent(instanceId)}/mcp`
    ),
    { fetch: proxyFetch(deadline) }
  );
  const client = new Client(HOST_CLIENT_INFO);
  // Each request carries both bounds: `signal` ends it at the deadline (and
  // tells the server it was cancelled), `timeout` lifts the SDK's 60s default,
  // which the request that cold-starts an npx workload can exceed.
  const bounds = { timeout: MCP_APP_TIMEOUT_MS, signal: deadline };
  try {
    await client.connect(transport, bounds);
    return await operation(client, bounds);
  } finally {
    await transport.terminateSession().catch((error: unknown) => {
      console.warn(`MCP session for ${instanceId} was not terminated`, error);
    });
    await client.close();
  }
}

export async function readMcpAppUiResource(
  instanceId: string,
  uri: string
): Promise<McpAppUiResource> {
  return withProxyClient(instanceId, async (client, bounds) =>
    uiResourceFromReadResult(await client.readResource({ uri }, bounds), uri)
  );
}

export async function callMcpAppTool(
  instanceId: string,
  name: string,
  args: Record<string, unknown>
): Promise<CallToolResult> {
  return withProxyClient(instanceId, (client, bounds) =>
    client.callTool({ name, arguments: args }, bounds)
  );
}

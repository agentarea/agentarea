// MCP Apps host calls, spoken as MCP to the governed per-connection proxy
// (/v1/mcp/{instance_id}/mcp). The proxy owns access control, governance on
// tools/call, and credential injection; nothing here re-implements them.

import "server-only";
import { setTimeout as delay } from "node:timers/promises";
import {
  Client,
  ProtocolError,
  ProtocolErrorCode,
  StreamableHTTPClientTransport,
  type CallToolResult,
  type ClientOptions,
  type PriorDiscovery,
} from "@modelcontextprotocol/client";
import { RESOURCE_MIME_TYPE } from "@modelcontextprotocol/ext-apps/app-bridge";
import { EXTENSION_ID } from "@modelcontextprotocol/ext-apps/server";
import { env } from "@/env";
import { MCP_APP_TIMEOUT_MS } from "@/lib/server-timeouts";
import { workspaceFetch } from "@/lib/workspace-request";
import { uiResourceFromReadResult, type McpAppUiResource } from "./tools";

const HOST_CLIENT_INFO = {
  name: "AgentArea MCP Apps host",
  version: "0.1.0",
} as const;
// Probe with server/discover and speak 2026-07-28 to servers that answer it;
// fall back to the initialize handshake for 2025-era servers. The UI
// extension tells servers that gate app tools on it that this host renders them.
const HOST_CLIENT_OPTIONS = {
  capabilities: {
    extensions: { [EXTENSION_ID]: { mimeTypes: [RESOURCE_MIME_TYPE] } },
  },
  versionNegotiation: { mode: "auto" },
} satisfies ClientOptions;
// Set by the manager's demand gateway (mcpgateway.StartingHeader) on its own
// "workload is starting" 503; the proxy passes it through.
const GATEWAY_STARTING_HEADER = "x-agentarea-mcp-starting";
// Closing the session is best effort and must still run after the deadline.
const SESSION_CLOSE_TIMEOUT_MS = 5_000;
// Errors that mean the server did not run the operation because the cached
// era verdict no longer matches it (for example a 2026 server replaced by a
// 2025 one).
const STALE_VERDICT_CODES: ReadonlySet<number> = new Set([
  ProtocolErrorCode.UnsupportedProtocolVersion,
  ProtocolErrorCode.MethodNotFound,
]);

/**
 * The protocol era each connection's server negotiated, by instance. Connecting
 * with it skips the server/discover probe (2026 servers: one request per call)
 * or goes straight to the handshake (2025 servers).
 */
const eraVerdicts = new Map<string, PriorDiscovery>();

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

async function connectAndRun<T>(
  instanceId: string,
  deadline: AbortSignal,
  prior: PriorDiscovery | undefined,
  operation: (
    client: Client,
    bounds: { timeout: number; signal: AbortSignal }
  ) => Promise<T>
): Promise<T> {
  const transport = new StreamableHTTPClientTransport(
    new URL(
      `${env.API_URL.replace(/\/+$/, "")}/v1/mcp/${encodeURIComponent(instanceId)}/mcp`
    ),
    { fetch: proxyFetch(deadline) }
  );
  const client = new Client(HOST_CLIENT_INFO, HOST_CLIENT_OPTIONS);
  // Each request carries both bounds: `signal` ends it at the deadline (and
  // tells the server it was cancelled), `timeout` lifts the SDK's 60s default,
  // which the request that cold-starts an npx workload can exceed.
  const bounds = { timeout: MCP_APP_TIMEOUT_MS, signal: deadline };
  try {
    await client.connect(transport, { ...bounds, prior });
    const discover = client.getDiscoverResult();
    eraVerdicts.set(
      instanceId,
      discover ? { kind: "modern", discover } : { kind: "legacy" }
    );
    return await operation(client, bounds);
  } finally {
    // A no-op on 2026 connections, which have no session to end.
    await transport.terminateSession().catch((error: unknown) => {
      console.warn(`MCP session for ${instanceId} was not terminated`, error);
    });
    await client.close();
  }
}

async function withProxyClient<T>(
  instanceId: string,
  operation: (
    client: Client,
    bounds: { timeout: number; signal: AbortSignal }
  ) => Promise<T>
): Promise<T> {
  const deadline = AbortSignal.timeout(MCP_APP_TIMEOUT_MS);
  const prior = eraVerdicts.get(instanceId);
  try {
    return await connectAndRun(instanceId, deadline, prior, operation);
  } catch (error) {
    if (
      !prior ||
      !(error instanceof ProtocolError) ||
      !STALE_VERDICT_CODES.has(error.code)
    ) {
      throw error;
    }
    eraVerdicts.delete(instanceId);
    return connectAndRun(instanceId, deadline, undefined, operation);
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

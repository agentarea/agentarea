import { NextResponse } from "next/server";
import { zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath } from "@/api/client/zod.gen";
import { getMCPServerInstance } from "@/lib/api";
import { apiErrorMessage, getApiStatus } from "@/lib/api-errors";
import { readMcpAppUiResource } from "@/lib/apps/mcp/proxy-client";
import type { ChatMcpAppResource } from "@/lib/apps/mcp/chat";
import { mcpAppEntries } from "@/lib/apps/mcp/tools";

function failure(detail: string, status: number) {
  return NextResponse.json({ detail }, { status });
}

/**
 * The view of an MCP App a conversation shows over an agent's tool call: the
 * entry tool's UI resource, read through the governed per-connection proxy.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ instanceId: string; toolName: string }> }
) {
  const { instanceId, toolName } = await params;
  const path =
    zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath.safeParse({
      instance_id: instanceId,
    });
  if (!path.success) return failure("Invalid MCP connection id", 400);

  const instance = await getMCPServerInstance(path.data.instance_id);
  if (!instance.data) {
    const status = getApiStatus(instance) ?? 502;
    return failure(
      apiErrorMessage(instance, "MCP connection could not be loaded"),
      status === 403 ? 404 : status
    );
  }
  const entry = mcpAppEntries([instance.data]).find(
    (candidate) => candidate.toolName === toolName
  );
  if (!entry) {
    return failure(`Tool "${toolName}" is not an MCP App entry point`, 404);
  }
  try {
    const body: ChatMcpAppResource = {
      title: entry.title || entry.toolName,
      resource: await readMcpAppUiResource(entry.instanceId, entry.resourceUri),
    };
    return NextResponse.json(body, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    console.error(`MCP App resource ${instanceId}/${toolName}`, error);
    return failure(error instanceof Error ? error.message : String(error), 502);
  }
}

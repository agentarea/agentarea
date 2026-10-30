import type { CallToolResult } from "@modelcontextprotocol/client";
import { TOOL_RESULT, type Part } from "@/lib/events/contract";
import type { McpAppUiResource } from "./tools";

/**
 * The MCP App a finished tool call opens in a conversation. The app is shown
 * over the agent's own call: its arguments and result, never a second call.
 */
export type ChatMcpApp = {
  instanceId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  result: CallToolResult;
};

/** What `/api/mcp-apps/{instance}/{tool}` answers: the app's view to render. */
export type ChatMcpAppResource = {
  title: string;
  resource: McpAppUiResource;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/**
 * The app a `tool.result` part opens, or null. The platform names the raw
 * tool in `mcp_app_tool` only when the call opens an app; a failed call opens
 * none. The transcript hands the app's own row the same part as kind "app".
 */
export function chatMcpApp(part: Part): ChatMcpApp | null {
  if (part.kind !== "tool" && part.kind !== "app") return null;
  if (part.eventType !== TOOL_RESULT) return null;
  const { data } = part;
  const toolName = nonEmpty(data.mcp_app_tool);
  const instanceId = nonEmpty(data.server_instance_id);
  if (!toolName || !instanceId || data.success === false) return null;
  const text =
    typeof data.result === "string"
      ? data.result
      : data.result == null
        ? ""
        : JSON.stringify(data.result);
  return {
    instanceId,
    toolName,
    arguments: isRecord(data.arguments) ? data.arguments : {},
    result: {
      content: text ? [{ type: "text", text }] : [],
      ...(isRecord(data.structured_content)
        ? { structuredContent: data.structured_content }
        : {}),
    },
  };
}

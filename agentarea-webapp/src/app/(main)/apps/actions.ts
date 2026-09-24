"use server";

import type { CallToolResult } from "@modelcontextprotocol/client";
import { z } from "zod";
import { zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath } from "@/api/client/zod.gen";
import { getMCPServerInstance } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  callMcpAppTool,
  readMcpAppUiResource,
} from "@/lib/mcp-apps/proxy-client";
import {
  mcpAppEntries,
  mcpAppLinkArguments,
  resolveMcpAppTool,
  type McpAppCaller,
  type McpAppUiResource,
} from "@/lib/mcp-apps/tools";

// The actions return failures instead of throwing: production Next.js
// replaces a thrown server-action error with a generic message, and the reason
// (a governance denial, a tool the app may not call) is what the user needs.

const zInstanceId =
  zGetMcpServerInstanceV1McpServerInstancesInstanceIdGetPath.shape.instance_id;

const zToolArguments = z.record(z.unknown());

const zAppToolCall = z.object({
  instanceId: zInstanceId,
  name: z.string().min(1),
  arguments: zToolArguments,
});

const zAppLink = z.object({
  instanceId: zInstanceId,
  toolName: z.string().min(1),
  params: z.record(z.string()),
});

async function loadInstance(instanceId: string) {
  const result = await getMCPServerInstance(instanceId);
  if (!result.data) {
    throw new Error(
      apiErrorMessage(result, "MCP connection could not be loaded")
    );
  }
  return result.data;
}

/**
 * As the MCP Apps host, this is where the visibility rules are enforced; the
 * proxy then applies access control and governance like it does for every
 * other MCP client.
 */
async function callAllowedTool(
  instanceId: string,
  name: string,
  args: Record<string, unknown>,
  caller: McpAppCaller
): Promise<CallToolResult> {
  resolveMcpAppTool(await loadInstance(instanceId), name, caller);
  return callMcpAppTool(instanceId, name, args);
}

/** Start an app: call its entry tool with the arguments it was opened with. */
export async function startMcpAppAction(
  instanceId: string,
  toolName: string,
  args: Record<string, unknown>
): Promise<
  { ok: true; result: CallToolResult } | { ok: false; error: string }
> {
  try {
    const id = zInstanceId.parse(instanceId);
    return {
      ok: true,
      result: await callAllowedTool(
        id,
        toolName,
        zToolArguments.parse(args),
        "host"
      ),
    };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export type OpenedMcpApp = {
  toolName: string;
  title: string;
  resource: McpAppUiResource;
  arguments: Record<string, unknown>;
};

/**
 * Resolve an app link from an open app into another UI of the same
 * connection: its resource and the arguments to start it with. Nothing is
 * called yet; the frame that renders the UI starts it.
 */
export async function openMcpAppLinkAction(
  instanceId: string,
  toolName: string,
  params: Record<string, string>
): Promise<{ ok: true; app: OpenedMcpApp } | { ok: false; error: string }> {
  try {
    const link = zAppLink.parse({ instanceId, toolName, params });
    const instance = await loadInstance(link.instanceId);
    const tool = resolveMcpAppTool(instance, link.toolName, "link");
    const entry = mcpAppEntries([instance]).find(
      (candidate) => candidate.toolName === link.toolName
    );
    if (!entry) {
      throw new Error(`Tool "${link.toolName}" is not an MCP App entry point`);
    }
    return {
      ok: true,
      app: {
        toolName: entry.toolName,
        title: entry.title || entry.toolName,
        resource: await readMcpAppUiResource(
          link.instanceId,
          entry.resourceUri
        ),
        arguments: mcpAppLinkArguments(tool, link.params),
      },
    };
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

/**
 * A tool call from an open app. A failure comes back as an MCP tool error, so
 * the app handles it like any other failed tool.
 */
export async function callMcpAppToolAction(
  instanceId: string,
  name: string,
  args: Record<string, unknown>
): Promise<CallToolResult> {
  try {
    const call = zAppToolCall.parse({ instanceId, name, arguments: args });
    return await callAllowedTool(
      call.instanceId,
      call.name,
      call.arguments,
      "app"
    );
  } catch (error) {
    return {
      isError: true,
      content: [
        {
          type: "text",
          text: error instanceof Error ? error.message : String(error),
        },
      ],
    };
  }
}

import type { CallToolResult } from "@modelcontextprotocol/client";
import type { App } from "@modelcontextprotocol/ext-apps";
import { toast } from "sonner";

/** The structured payload of a tool result, or the tool's own error message. */
export function structured<T>(result: CallToolResult): T {
  if (result.isError) {
    const message = result.content
      .map((block) => (block.type === "text" ? block.text : ""))
      .join(" ")
      .trim();
    throw new Error(message || "The tool reported an error");
  }
  if (!result.structuredContent) throw new Error("The tool returned no structured content");
  return result.structuredContent as T;
}

export const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

/**
 * Asks the host to open another UI of this same MCP connection. AgentArea
 * understands `agentarea-app://<tool>?<arg>=<value>`: it calls that tool and
 * shows the UI it points at, coercing each value by the tool's input schema.
 */
export async function openAppView(app: App, tool: string, args: Record<string, string>): Promise<void> {
  const url = `agentarea-app://${tool}?${new URLSearchParams(args)}`;
  try {
    const { isError } = await app.openLink({ url });
    if (isError) {
      toast.error("The host couldn't open this view", { description: `It declined ${url}` });
    }
  } catch (error) {
    toast.error("The host couldn't open this view", { description: messageOf(error) });
  }
}

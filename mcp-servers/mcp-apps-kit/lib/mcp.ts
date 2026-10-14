import type { CallToolResult } from "@modelcontextprotocol/client";
import type { App } from "@modelcontextprotocol/ext-apps";
import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { useState } from "react";

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

export async function call<T>(app: App, name: string, args: Record<string, unknown>): Promise<T> {
  return structured<T>(await app.callServerTool({ name, arguments: args }));
}

/**
 * Asks the host to open another UI of this same MCP connection. AgentArea
 * understands `agentarea-app://<tool>?<arg>=<value>`: it calls that tool and
 * shows the UI it points at, coercing each value by the tool's input schema.
 *
 * Resolves to null when the host took the link, or to the reason it did not.
 */
export async function openAppView(app: App, tool: string, args: Record<string, string>): Promise<string | null> {
  const url = `agentarea-app://${tool}?${new URLSearchParams(args)}`;
  try {
    const { isError } = await app.openLink({ url });
    return isError ? `The host declined to open ${url}` : null;
  } catch (error) {
    return `The host couldn't open this view: ${messageOf(error)}`;
  }
}

/**
 * One view's connection to its host: the bridge, the entry tool's input and
 * result, and the view's own payload state seeded from that result.
 */
export function useView<T>(name: string, onInput?: (input: Record<string, unknown>) => void) {
  const [payload, setPayload] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const {
    app,
    isConnected,
    error: connectError,
  } = useApp({
    appInfo: { name, version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (input) onInput?.(input);
      });
      // The entry tool's own result: use it if nothing newer has loaded yet.
      created.addEventListener("toolresult", (result) => {
        try {
          const incoming = structured<T>(result);
          setPayload((current) => current ?? incoming);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled ${name}: ${reason}` : `The host cancelled ${name}`);
      });
    },
  });
  useHostStyles(app, app?.getHostContext());
  return { app, isConnected, payload, setPayload, error: connectError?.message ?? error, setError };
}

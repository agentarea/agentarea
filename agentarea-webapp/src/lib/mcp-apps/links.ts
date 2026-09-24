/**
 * An app opens another UI of its own connection by asking the host to open
 * `agentarea-app://<toolName>?<param>=<value>&…`. It rides the open-link
 * request MCP Apps already define, so apps need no protocol extension.
 */
export const MCP_APP_LINK_PROTOCOL = "agentarea-app:";

export type McpAppLink = {
  toolName: string;
  params: Record<string, string>;
};

/** The target of an app link, or null when the URL is not one. */
export function parseMcpAppLink(url: string): McpAppLink | null {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  if (parsed.protocol !== MCP_APP_LINK_PROTOCOL) return null;
  // `agentarea-app://tool` puts the name in the host, `agentarea-app:tool`
  // in the path; both are accepted, and nothing else may follow it.
  if (parsed.host && parsed.pathname !== "" && parsed.pathname !== "/") {
    return null;
  }
  const target = parsed.host || parsed.pathname;
  let toolName: string;
  try {
    toolName = decodeURIComponent(target);
  } catch {
    return null;
  }
  if (!toolName || toolName.includes("/")) return null;
  return { toolName, params: Object.fromEntries(parsed.searchParams) };
}

import { cache } from "react";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import { getMCPServer, getMCPServerInstance } from "@/lib/api";
import { optionalApiData, requireApiData } from "@/lib/server-resource";

/**
 * Request-memoized connection fetch: the layout (header, tab counts) and the
 * tab page both read the instance, and React `cache` makes that one request.
 */
export const getInstanceCached = cache(async (id: string) =>
  requireApiData(await getMCPServerInstance(id), "MCP instance")
);

/** The catalog server the instance was made from, or null when it has none left. */
export async function loadServerSpec(instance: McpServerInstanceResponse) {
  if (!instance.server_spec_id) return null;
  return optionalApiData(
    await getMCPServer(instance.server_spec_id),
    `MCP server ${instance.server_spec_id}`
  );
}

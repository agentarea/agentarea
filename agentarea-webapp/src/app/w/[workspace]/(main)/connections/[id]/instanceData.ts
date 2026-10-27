import { cache } from "react";
import { getMCPServerInstance } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";

/**
 * Request-memoized connection fetch: the layout (header, tab counts) and the
 * tab page both read the instance, and React `cache` makes that one request.
 */
export const getInstanceCached = cache(async (id: string) =>
  requireApiData(await getMCPServerInstance(id), "MCP instance")
);

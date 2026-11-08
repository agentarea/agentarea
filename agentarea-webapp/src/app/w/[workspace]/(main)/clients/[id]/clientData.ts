import { cache } from "react";
import { getClient } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";

/**
 * Request-memoized harness fetch: the layout (header, tab counts) and the tab
 * page both read the client, and React `cache` makes that one request.
 */
export const getClientCached = cache(async (id: string) =>
  requireApiData(await getClient(id), "harness")
);

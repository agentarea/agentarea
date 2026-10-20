import { cache } from "react";
import { getOpenAPIConnection } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import type { OpenAPIConnection } from "../../types";

/**
 * Request-memoized connection fetch: the layout (header, tab count) and the
 * tab page both read it, and React `cache` makes that one request. A missing
 * connection is a 404 page; a failed load goes to the error boundary.
 */
export const getOpenAPIConnectionCached = cache(
  async (id: string): Promise<OpenAPIConnection> =>
    requireApiData(await getOpenAPIConnection(id), "OpenAPI connection")
);

import type { CatalogConnection } from "@/api/client/types.gen";

/** The connections list param that narrows it to one catalog item's connections. */
export const CATALOG_SOURCE_PARAM = "source";

export function connectionHref(
  connection: Pick<CatalogConnection, "id" | "kind">
): string {
  return connection.kind === "openapi"
    ? `/connections/openapi/${connection.id}`
    : `/connections/${connection.id}`;
}

/**
 * Where "Open" goes for a catalog item already connected: the connection
 * itself when there is one, the list narrowed to the item when there are more.
 */
export function existingConnectionsHref(
  itemId: string,
  connections: Pick<CatalogConnection, "id" | "kind">[]
): string | null {
  if (connections.length === 0) return null;
  if (connections.length === 1) return connectionHref(connections[0]);
  return `/connections?${CATALOG_SOURCE_PARAM}=${encodeURIComponent(itemId)}`;
}

export function parseCatalogSource(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/**
 * The instances and API connections made from one catalog item. An instance
 * names its item through its spec, so a spec missing from `specs` excludes it.
 */
export function fromCatalogItem<
  I extends { server_spec_id: string },
  O extends { registry_item_id?: string | null },
>(
  itemId: string,
  instances: I[],
  specs: { id: string; registry_item_id?: string | null }[],
  openApiConnections: O[]
): { instances: I[]; openApiConnections: O[] } {
  const specsFromItem = new Set(
    specs.filter((spec) => spec.registry_item_id === itemId).map((s) => s.id)
  );
  return {
    instances: instances.filter((i) => specsFromItem.has(i.server_spec_id)),
    openApiConnections: openApiConnections.filter(
      (c) => c.registry_item_id === itemId
    ),
  };
}

import type { RegistryResponse } from "@/api/client/types.gen";

/** What a registry row shows in either section of the page. */
export type RegistryRow = Pick<
  RegistryResponse,
  | "id"
  | "name"
  | "description"
  | "registry_type"
  | "mode"
  | "trust"
  | "item_count"
  | "is_active"
  | "last_synced_at"
  | "last_sync_error"
>;

/**
 * A platform registry as the page renders it. Its source and credentials are
 * the operator's deployment config, so they stay on the server.
 */
export function toPlatformRegistryRow(registry: RegistryResponse): RegistryRow {
  return {
    id: registry.id,
    name: registry.name,
    description: registry.description,
    registry_type: registry.registry_type,
    mode: registry.mode,
    trust: registry.trust,
    item_count: registry.item_count,
    is_active: registry.is_active,
    last_synced_at: registry.last_synced_at,
    last_sync_error: registry.last_sync_error,
  };
}

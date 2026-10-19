import { describe, expect, it } from "vitest";
import type { RegistryResponse } from "@/api/client/types.gen";
import { toPlatformRegistryRow } from "./registry-rows";

const platformRegistry: RegistryResponse = {
  id: "5b7c0d2e-0000-4000-8000-000000000001",
  name: "system-skills-curated",
  description: "Curated skills",
  registry_type: "skills",
  source_type: "github",
  source_url: "internal-org/private-skills",
  source_ref: "main",
  source_path: "skills",
  sync_mode: "auto",
  is_active: true,
  scope: "platform",
  workspace_id: null,
  mode: "mirror",
  trust: "official",
  credentials_secret_id: "5b7c0d2e-0000-4000-8000-000000000002",
  last_synced_at: "2026-10-19T10:00:00Z",
  last_sync_error: null,
  item_count: 42,
  recommendation_priority: 0,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-19T10:00:00Z",
};

describe("platform registry row", () => {
  it("keeps what the table shows and leaves the operator's source behind", () => {
    const row = toPlatformRegistryRow(platformRegistry);

    expect(row).toEqual({
      id: platformRegistry.id,
      name: "system-skills-curated",
      description: "Curated skills",
      registry_type: "skills",
      mode: "mirror",
      trust: "official",
      item_count: 42,
      is_active: true,
      last_synced_at: "2026-10-19T10:00:00Z",
      last_sync_error: null,
    });
  });
});

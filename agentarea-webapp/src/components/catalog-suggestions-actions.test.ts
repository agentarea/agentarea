import { beforeEach, describe, expect, it, vi } from "vitest";
import { listCatalogSuggestionsAction } from "./catalog-suggestions-actions";

const { browseCatalog, listRegistries, listRegistryItems } = vi.hoisted(() => ({
  browseCatalog: vi.fn(),
  listRegistries: vi.fn(),
  listRegistryItems: vi.fn(),
}));

vi.mock("server-only", () => ({}));
vi.mock("@/lib/api", () => ({
  browseCatalog,
  listRegistries,
  listRegistryItems,
}));

const NOW = "2026-09-06T00:00:00Z";
const REGISTRY_ID = "00000000-0000-4000-8000-000000000001";

function item(
  id: string,
  name: string,
  stars: number,
  repo: string,
  description: string
) {
  return {
    id,
    registry_id: REGISTRY_ID,
    external_id: name,
    name,
    description,
    version: "1.0.0",
    spec: {
      original_name: name.split("--")[0],
      provenance: { stars, repo },
      content: "full skill content must not reach the client DTO",
    },
    tags: [`repo:${repo.replaceAll("/", "-")}`, "category:development"],
    installed_entity_id: null,
    update_available: false,
    installed_version: null,
    category: "development",
    featured: false,
    created_at: NOW,
    updated_at: NOW,
  };
}

describe("listCatalogSuggestionsAction", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listRegistries.mockResolvedValue({
      data: [
        {
          id: REGISTRY_ID,
          name: "skills-catalog",
          description: "Curated skills",
          registry_type: "skills",
          source_type: "url",
          source_url:
            "https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/skills.json",
          sync_mode: "manual",
          is_active: true,
          last_synced_at: NOW,
          last_sync_error: null,
          item_count: 4,
          created_at: NOW,
          updated_at: NOW,
        },
      ],
      error: null,
    });
    listRegistryItems.mockResolvedValue({
      data: [
        item(
          "00000000-0000-4000-8000-000000000006",
          "unknown--popular-repo--feedface",
          100_000,
          "popular/repo",
          "A repository description accidentally imported as a skill."
        ),
        item(
          "00000000-0000-4000-8000-000000000002",
          "0-autoresearch-skill--openraiser-nanoresearch--deadbeef",
          12,
          "openraiser/nanoresearch",
          "An obscure imported research workflow."
        ),
        item(
          "00000000-0000-4000-8000-000000000003",
          "frontend-design--anthropics-claude-code--abc123",
          47_860,
          "anthropics/claude-code",
          "Create polished production interfaces."
        ),
        item(
          "00000000-0000-4000-8000-000000000004",
          "mcp-builder--anthropics-skills--def456",
          9_200,
          "anthropics/skills",
          "Build reliable MCP servers and integrations."
        ),
      ],
      error: null,
    });
    browseCatalog.mockResolvedValue({
      items: [],
      total: 0,
      categories: [],
      error: null,
    });
  });

  it("uses one curated registry request and returns popular human-readable DTOs", async () => {
    const result = await listCatalogSuggestionsAction("skills", 2);

    expect(listRegistries).toHaveBeenCalledOnce();
    expect(listRegistryItems).toHaveBeenCalledOnce();
    expect(browseCatalog).not.toHaveBeenCalled();
    expect(result).toEqual([
      {
        id: "00000000-0000-4000-8000-000000000003",
        title: "Frontend Design",
        description: "Create polished production interfaces.",
        iconUrl: null,
        source: "anthropics/claude-code",
        popularityLabel: "47.9K stars",
      },
      {
        id: "00000000-0000-4000-8000-000000000004",
        title: "MCP Builder",
        description: "Build reliable MCP servers and integrations.",
        iconUrl: null,
        source: "anthropics/skills",
        popularityLabel: "9.2K stars",
      },
    ]);
    expect(result[0]).not.toHaveProperty("spec");
  });

  it("uses the unified browse endpoint for catalog types without a curated source", async () => {
    listRegistries.mockResolvedValue({ data: [], error: null });
    browseCatalog.mockResolvedValue({
      items: [
        item(
          "00000000-0000-4000-8000-000000000005",
          "Support Agent",
          0,
          "agentarea/catalog",
          "Triage and resolve support requests."
        ),
      ],
      total: 1,
      categories: [],
      error: null,
    });

    const result = await listCatalogSuggestionsAction("agents", 6);

    expect(listRegistryItems).not.toHaveBeenCalled();
    expect(browseCatalog).toHaveBeenCalledWith({
      registryType: "agents",
      sort: "featured",
      limit: 24,
      offset: 0,
    });
    expect(result[0].title).toBe("Support Agent");
  });
});

import { describe, expect, it } from "vitest";
import {
  modelNameMatchesPreferred,
  normalize,
  normalizeModelSlug,
  type RegistryItem,
} from "../catalog-data";

function assertEqual<T>(actual: T, expected: T, name: string) {
  it(name, () => {
    expect(actual).toEqual(expected);
  });
}

function item(over: Partial<RegistryItem>): RegistryItem {
  return {
    id: "id-1",
    name: "Item",
    description: null,
    version: "1.0.0",
    tags: [],
    spec: {},
    ...over,
  };
}

describe("catalog data normalization", () => {
  // ── agents: preferred_models drives the model meta ──

  assertEqual(
    normalize(
      "agents",
      item({
        name: "Data Analyst",
        spec: { preferred_models: ["gpt-4o", "o3"] },
      })
    ).meta,
    ["gpt-4o", "o3"],
    "agent: preferred_models shown in priority order"
  );

  assertEqual(
    normalize("agents", item({ name: "None", spec: {} })).meta,
    [],
    "agent: no model → empty meta (no bogus 'model not set')"
  );

  assertEqual(
    normalize(
      "agents",
      item({ name: "Support", tags: ["support", "ops"], spec: {} })
    ).category,
    "support",
    "agent: first tag becomes category"
  );

  // ── skills: title prettification + repo meta ──

  assertEqual(
    normalize(
      "skills",
      item({
        name: "frontend-design--anthropics-claude-code--524b3f2b0b",
        tags: ["repo:anthropics-claude-code", "category:design"],
      })
    ).title,
    "Frontend Design",
    "skill: '--' separated id → head segment prettified"
  );

  assertEqual(
    normalize(
      "skills",
      item({
        name: "claude-opus-4-5-migration-anthropics-claude-code",
        tags: ["repo:anthropics-claude-code"],
      })
    ).title,
    "Claude Opus 4 5 Migration",
    "skill: repo suffix stripped when no '--' separator"
  );

  assertEqual(
    normalize(
      "skills",
      item({
        name: "docx--anthropics-skills--610c2c1ef9",
        tags: ["repo:anthropics-skills"],
      })
    ).meta,
    ["anthropics-skills"],
    "skill: repo shown as card meta (not source_type)"
  );

  assertEqual(
    normalize(
      "skills",
      item({ name: "x--y--z", tags: ["category:design", "repo:y"] })
    ).category,
    "design",
    "skill: category from category: tag"
  );

  assertEqual(
    normalize("skills", item({ name: "no-repo-skill", tags: [], spec: {} }))
      .meta,
    [],
    "skill: no repo tag → empty meta"
  );

  assertEqual(
    normalize(
      "skills",
      item({
        name: "whatever--y--z",
        tags: ["repo:y"],
        spec: { display_name: "Nice Name" },
      })
    ).title,
    "Nice Name",
    "skill: explicit display_name wins over generated title"
  );

  assertEqual(
    normalize(
      "skills",
      item({
        name: "mcp-builder--anthropics-skills--abc123",
        tags: ["repo:anthropics-skills"],
        spec: { original_name: "mcp-builder" },
      })
    ).title,
    "MCP Builder",
    "skill: original name keeps meaningful words and common acronyms"
  );

  // ── server-derived facets win over local re-derivation ──
  // Browsing is filtered, sorted and counted in SQL against the row's stored
  // category/featured columns. If a card re-derived them and disagreed, an item
  // could sit under a facet whose filter would never return it.

  assertEqual(
    normalize(
      "skills",
      item({
        name: "x--y--z",
        tags: ["category:design"],
        category: "documents",
      })
    ).category,
    "documents",
    "facets: server category wins over the tag-derived one"
  );

  assertEqual(
    normalize("skills", item({ name: "x--y--z", tags: ["category:design"] }))
      .category,
    "design",
    "facets: falls back to local derivation when the server sent none"
  );

  assertEqual(
    normalize("skills", item({ name: "x", tags: [], featured: true })).featured,
    true,
    "facets: server featured flag is respected"
  );

  assertEqual(
    normalize("skills", item({ name: "x", tags: ["featured"] })).featured,
    true,
    "facets: falls back to the featured tag when the server sent no flag"
  );

  // ── icon candidates (the card falls through these on a 404) ──
  // One URL was not enough: the curated connection catalog ships a local icon
  // *and* a hosted fallback, and a card that gave up on the first failure
  // showed the same generic glyph as every other card on the page.

  assertEqual(
    normalize(
      "connections",
      item({
        name: "GitHub",
        spec: {
          raw_spec: {
            icons: [{ src: "/api/static/icons/mcp/github.ico" }],
            metadata: {
              "agentarea:logo_source_url": "https://cdn.test/github.png",
            },
          },
        },
      })
    ).identity.sources,
    ["/api/static/icons/mcp/github.ico", "https://cdn.test/github.png"],
    "icons: the curated fallback is kept behind the primary logo"
  );

  assertEqual(
    normalize(
      "connections",
      item({
        name: "Dupe",
        spec: {
          icon: "https://cdn.test/a.png",
          raw_spec: { icons: [{ src: "https://cdn.test/a.png" }] },
        },
      })
    ).identity.sources,
    ["https://cdn.test/a.png"],
    "icons: the same URL twice is one candidate, not a retry of a failure"
  );

  assertEqual(
    normalize(
      "connections",
      item({
        name: "Hostile",
        spec: { icon: "javascript:alert(1)", icon_url: "cdn.test/x.png" },
      })
    ).identity.sources,
    [],
    "icons: only app-relative paths and http(s) URLs reach an <img src>"
  );

  assertEqual(
    normalize(
      "skills",
      item({
        name: "pdf--anthropics-skills--abc",
        spec: { provenance: { repo: "anthropics/skills" } },
      })
    ).identity.sources,
    ["https://github.com/anthropics.png?size=128"],
    "icons: a skill with no artwork borrows its publisher's avatar"
  );

  assertEqual(
    normalize("agents", item({ name: "Plain", spec: {} })).identity.sources,
    [],
    "icons: nothing usable → no candidates (the card draws a monogram)"
  );

  // ── tolerant model matching (drives the "preferred models" suggestion) ──

  assertEqual(
    normalizeModelSlug("openai/gpt-4o-mini"),
    "gpt4omini",
    "normalize: drops provider prefix"
  );
  assertEqual(
    normalizeModelSlug("GPT-4o"),
    "gpt4o",
    "normalize: lowercases + strips punctuation"
  );

  assertEqual(
    modelNameMatchesPreferred("openai/gpt-4o-mini", "gpt-4o"),
    true,
    "match: bare slug matches provider-prefixed variant"
  );
  assertEqual(
    modelNameMatchesPreferred("openai/gpt-4o", "gpt-4o"),
    true,
    "match: exact family after prefix strip"
  );
  assertEqual(
    modelNameMatchesPreferred("anthropic/claude-3-opus", "gpt-4o"),
    false,
    "match: unrelated model does not match"
  );
  assertEqual(
    modelNameMatchesPreferred("minimax/minimax-m2.7", "o3"),
    false,
    "match: short slug does not spuriously match"
  );
  assertEqual(
    modelNameMatchesPreferred("", "gpt-4o"),
    false,
    "match: empty model name → false"
  );
});

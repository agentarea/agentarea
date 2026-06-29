/**
 * Tests for the catalog normalize() data layer (pure functions).
 * Run with: npx tsx "src/app/(main)/bundles/components/__tests__/catalog-data.test.ts"
 */
import {
  modelNameMatchesPreferred,
  normalize,
  normalizeModelSlug,
  type RegistryItem,
} from "../catalog-data";

let failed = 0;
function assertEqual<T>(actual: T, expected: T, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    failed += 1;
    console.error(
      `FAIL ${name}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`,
    );
  } else {
    console.log(`PASS ${name}`);
  }
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

// ── agents: preferred_models drives the model meta ──

assertEqual(
  normalize("agents", item({ name: "Data Analyst", spec: { preferred_models: ["gpt-4o", "o3"] } }))
    .meta,
  ["gpt-4o", "o3"],
  "agent: preferred_models shown in priority order",
);

assertEqual(
  normalize("agents", item({ name: "Legacy", spec: { model_id: "gpt-4o" } })).meta,
  ["gpt-4o"],
  "agent: legacy model_id slug used as fallback",
);

assertEqual(
  normalize("agents", item({ name: "Both", spec: { preferred_models: ["o3"], model_id: "gpt-4o" } }))
    .meta,
  ["o3"],
  "agent: preferred_models wins over legacy model_id",
);

assertEqual(
  normalize("agents", item({ name: "None", spec: {} })).meta,
  [],
  "agent: no model → empty meta (no bogus 'model not set')",
);

assertEqual(
  normalize("agents", item({ name: "Support", tags: ["support", "ops"], spec: {} })).category,
  "support",
  "agent: first tag becomes category",
);

// ── skills: title prettification + repo meta ──

assertEqual(
  normalize(
    "skills",
    item({
      name: "frontend-design--anthropics-claude-code--524b3f2b0b",
      tags: ["repo:anthropics-claude-code", "category:design"],
    }),
  ).title,
  "Frontend Design",
  "skill: '--' separated id → head segment prettified",
);

assertEqual(
  normalize(
    "skills",
    item({
      name: "claude-opus-4-5-migration-anthropics-claude-code",
      tags: ["repo:anthropics-claude-code"],
    }),
  ).title,
  "Claude Opus 4 5 Migration",
  "skill: repo suffix stripped when no '--' separator",
);

assertEqual(
  normalize(
    "skills",
    item({ name: "docx--anthropics-skills--610c2c1ef9", tags: ["repo:anthropics-skills"] }),
  ).meta,
  ["anthropics-skills"],
  "skill: repo shown as card meta (not source_type)",
);

assertEqual(
  normalize(
    "skills",
    item({ name: "x--y--z", tags: ["category:design", "repo:y"] }),
  ).category,
  "design",
  "skill: category from category: tag",
);

assertEqual(
  normalize("skills", item({ name: "no-repo-skill", tags: [], spec: {} })).meta,
  [],
  "skill: no repo tag → empty meta",
);

assertEqual(
  normalize(
    "skills",
    item({ name: "whatever--y--z", tags: ["repo:y"], spec: { display_name: "Nice Name" } }),
  ).title,
  "Nice Name",
  "skill: explicit display_name wins over generated title",
);

// ── tolerant model matching (drives the "preferred models" suggestion) ──

assertEqual(normalizeModelSlug("openai/gpt-4o-mini"), "gpt4omini", "normalize: drops provider prefix");
assertEqual(normalizeModelSlug("GPT-4o"), "gpt4o", "normalize: lowercases + strips punctuation");

assertEqual(
  modelNameMatchesPreferred("openai/gpt-4o-mini", "gpt-4o"),
  true,
  "match: bare slug matches provider-prefixed variant",
);
assertEqual(
  modelNameMatchesPreferred("openai/gpt-4o", "gpt-4o"),
  true,
  "match: exact family after prefix strip",
);
assertEqual(
  modelNameMatchesPreferred("anthropic/claude-3-opus", "gpt-4o"),
  false,
  "match: unrelated model does not match",
);
assertEqual(
  modelNameMatchesPreferred("minimax/minimax-m2.7", "o3"),
  false,
  "match: short slug does not spuriously match",
);
assertEqual(modelNameMatchesPreferred("", "gpt-4o"), false, "match: empty model name → false");

if (failed > 0) {
  console.error(`\n${failed} test(s) failed`);
  process.exit(1);
} else {
  console.log("\nAll tests passed");
}

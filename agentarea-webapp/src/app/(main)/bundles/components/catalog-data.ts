// Shared catalog data layer — types + normalization used by BOTH the server
// component (explore/page.tsx, first-page SSR) and the client gallery
// (CatalogGallery, infinite-scroll appends). No React/JSX here so it stays
// importable from a Server Component.

export type CatalogType = "bundles" | "agents" | "skills" | "mcp_servers";

export const TYPE_KEYS = [
  "bundles",
  "agents",
  "skills",
  "mcp_servers",
] as const satisfies readonly CatalogType[];

// Page size for a single registry fetch. A short page means "no more".
export const PAGE = 96;
// Sentinel for the "All categories" facet (kept out of the URL as a real value).
export const ALL = "__all__";
export const FEATURED_TAG = "featured";

export type RawSpec = Record<string, unknown>;

export type RegistryItem = {
  id: string;
  name: string;
  description: string | null;
  version: string | null;
  tags: string[];
  spec: RawSpec;
  installed_entity_id?: string | null;
};

export type Registry = { id: string; name: string; registry_type: string };

// Normalized shape every card/drawer renders from.
export type CatalogEntry = {
  id: string;
  type: CatalogType;
  title: string;
  description: string;
  tags: string[];
  category: string | null;
  integrations: string[]; // brand monograms on the card (bundles: their MCPs)
  meta: string[]; // small type-specific facts ("gpt-4o", "url", "3 agents")
  iconUrl: string | null; // brand logo when the source provides one
  featured: boolean; // hand-curated well-known entry (sorts first server-side)
  verified: boolean; // official vendor connection with confirmed OAuth
  installEntityId: string | null; // linked MCP spec id → existing create-from-spec page
  spec: RawSpec;
};

export function isCatalogType(v: unknown): v is CatalogType {
  return typeof v === "string" && (TYPE_KEYS as readonly string[]).includes(v);
}

export function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
export function arr(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? (v as Record<string, unknown>[]) : [];
}
export function strArr(v: unknown): string[] {
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string" && x.length > 0)
    : [];
}

// Best-effort logo URL from whatever the source preserved. MCP registry items
// keep the full upstream server object under spec.raw_spec, whose `icons` is a
// list of {src, mimeType}. Other types may carry a flat icon/metadata.icon.
export function extractIcon(spec: RawSpec): string | null {
  const raw = (spec.raw_spec as RawSpec | undefined) ?? spec;
  const icons = arr(raw.icons);
  if (icons.length > 0) {
    const src = str(icons[0].src);
    if (src) return src;
  }
  const meta = spec.metadata as RawSpec | undefined;
  return str(spec.icon) ?? str(spec.icon_url) ?? (meta ? str(meta.icon) : null);
}

// Registry skill ids look like "action-creator--owner-repo--<hash>": the part
// before the first "--" is the human name, the rest is provenance. Some sources
// instead append "-<repo-slug>" without the "--" separator
// ("frontend-design-anthropics-claude-code"); strip that using the repo tag so
// the title doesn't carry the repo. Turn the result into a readable title.
function prettifySkillName(name: string, repo?: string | null): string {
  let head = name.split("--")[0];
  if (head === name && repo) {
    const repoSlug = repo.replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    if (repoSlug && head.toLowerCase().endsWith(`-${repoSlug}`)) {
      head = head.slice(0, head.length - repoSlug.length - 1);
    }
  }
  head = head.replace(/[-_]+/g, " ").trim();
  return head.replace(/\b\w/g, (c) => c.toUpperCase()) || name;
}

export function normalize(type: CatalogType, item: RegistryItem): CatalogEntry {
  const spec = item.spec || {};
  const tags = item.tags || [];
  const base = {
    id: item.id,
    type,
    description: item.description || "",
    tags,
    iconUrl: extractIcon(spec),
    featured: tags.includes(FEATURED_TAG),
    verified: false,
    installEntityId: item.installed_entity_id ?? null,
    spec,
  };

  if (type === "bundles") {
    const meta = spec.metadata as RawSpec | undefined;
    const counts: string[] = [];
    const n = (k: string, label: string) => {
      const c = arr(spec[k]).length;
      if (c) counts.push(`${c} ${label}${c > 1 ? "s" : ""}`);
    };
    n("agents", "agent");
    n("skills", "skill");
    n("mcps", "connection");
    n("automations", "automation");
    return {
      ...base,
      title: str(spec.display_name) || str(spec.name) || item.name,
      category: str(meta?.category),
      integrations: arr(spec.mcps).map((m) => String(m.name ?? "")).filter(Boolean),
      meta: counts,
    };
  }
  if (type === "agents") {
    // Catalog agents declare model *preferences* (slugs, priority order) — a hint
    // for the UI to suggest a model. The backend never binds a concrete model on
    // install. Fall back to the legacy single ``model_id`` slug for not-yet-
    // resynced catalog data.
    const preferred = strArr(spec.preferred_models);
    const legacy = str(spec.model_id);
    const models = preferred.length > 0 ? preferred : legacy ? [legacy] : [];
    return {
      ...base,
      title: item.name,
      // Catalog agents carry domain tags (support, engineering, data…); the
      // first one is a sensible category.
      category: str(item.tags?.[0]),
      integrations: [],
      meta: models,
    };
  }
  if (type === "skills") {
    // Skills encode their category and source repo as "category:<x>" / "repo:<x>"
    // tags. Show the repo as the card fact (the "content" source_type is noise);
    // use it to strip the repo from the generated title too.
    const tagVal = (prefix: string) =>
      (item.tags ?? []).find((t) => t.startsWith(prefix))?.slice(prefix.length) ?? null;
    const repo = tagVal("repo:");
    return {
      ...base,
      title: str(spec.display_name) ?? prettifySkillName(item.name, repo),
      category: tagVal("category:"),
      integrations: [],
      meta: repo ? [repo] : [],
    };
  }
  // mcp_servers (connections). Category comes from curated metadata when the
  // source provides it (agentarea:category); transport (streamable-http,
  // command, sse…) is "how it connects", not a category, so we don't facet on it.
  const conn = str(spec.connection_type) ?? str(spec.transport) ?? "url";
  const rawMeta = (spec.raw_spec as RawSpec | undefined)?.metadata as RawSpec | undefined;
  return {
    ...base,
    title: item.name,
    category: str(rawMeta?.["agentarea:category"]),
    verified: rawMeta?.["agentarea:oauth_status"] === "verified",
    integrations: [],
    meta: [conn],
  };
}

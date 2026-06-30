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

// Per-path cookie that persists the grid/table choice across navigation. Lives
// here (not in the "use client" gallery) so the Server Components — explore
// page.tsx + loading.tsx — import the real string, not a client-reference proxy.
// Same `${param}_${path}` convention as HeaderTabs.
export const EXPLORE_VIEW_COOKIE = "view_explore";

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
// before the first "--" is the human name, the rest is provenance. Turn the
// leading segment into a readable title ("action-creator" -> "Action Creator").
function prettifySkillName(name: string): string {
  const head = name.split("--")[0].replace(/[-_]+/g, " ").trim();
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
    return {
      ...base,
      title: item.name,
      // Catalog agents carry domain tags (support, engineering, data…); the
      // first one is a sensible category.
      category: str(item.tags?.[0]),
      integrations: [],
      meta: [str(spec.model_id) ?? "model not set"],
    };
  }
  if (type === "skills") {
    // Skills encode their category as a "category:<x>" tag.
    const catTag = (item.tags ?? []).find((t) => t.startsWith("category:"));
    return {
      ...base,
      title: str(spec.display_name) ?? prettifySkillName(item.name),
      category: catTag ? catTag.slice("category:".length) : null,
      integrations: [],
      meta: [str(spec.source_type) ?? "content"],
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

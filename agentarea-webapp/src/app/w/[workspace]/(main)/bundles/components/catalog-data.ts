// Shared catalog data layer — types + normalization used by BOTH the server
// component (explore/page.tsx, first-page SSR) and the client gallery
// (CatalogGallery, infinite-scroll appends). No React/JSX here so it stays
// importable from a Server Component.

import type { EntityKind } from "@/lib/entity-icons";
import {
  domainInitials,
  faviconSources,
  type EntityIdentity,
} from "@/lib/entity-identity";

export type CatalogType = "bundles" | "agents" | "skills" | "connections";

export const TYPE_KEYS = [
  "bundles",
  "agents",
  "skills",
  "connections",
] as const satisfies readonly CatalogType[];

// The backend files every connection under the `mcp_servers` registry type.
// The tab is "connections" because that is what the entry is to a user: an
// account or service you wire up. How it is reached — the Model Context
// Protocol, or a plain HTTP API described by OpenAPI — is the `protocol`
// facet below, not the identity of the tab.
export const REGISTRY_TYPE: Record<CatalogType, string> = {
  bundles: "bundles",
  agents: "agents",
  skills: "skills",
  connections: "mcp_servers",
};

// What the connections tab used to be called. Links to it exist in docs, in
// the app itself and in bookmarks, so the old value still resolves.
const LEGACY_TYPES: Record<string, CatalogType> = { mcp_servers: "connections" };

// How a connection is reached. Mirrors CATALOG_PROTOCOLS on the backend, which
// derives it from `spec.connection_type` and rejects anything else.
export type CatalogProtocol = "mcp" | "api";
export const PROTOCOL_KEYS = [
  "mcp",
  "api",
] as const satisfies readonly CatalogProtocol[];
export const PROTOCOL_LABELS: Record<CatalogProtocol, string> = {
  mcp: "MCP",
  api: "HTTP API",
};
const OPENAPI_CONNECTION_TYPE = "openapi";

// Page size for a single registry fetch. A short page means "no more".
export const PAGE = 96;
// Sentinel for the "All categories" facet (kept out of the URL as a real value).
export const ALL = "__all__";
export const FEATURED_TAG = "featured";

// Catalog orderings, applied server-side. `recommended` is the catalog's own
// curation — hand-featured entries, then whole sources by weight, then each
// source's published order (the skills artifact is published in GitHub-star
// order, the connection artifact leads with the official integrations) — and
// `name` is a plain A→Z. Kept in sync with CATALOG_SORTS on the backend; an
// unknown value is rejected there rather than silently ignored.
export const SORT_KEYS = ["recommended", "name"] as const;
export type SortMode = (typeof SORT_KEYS)[number];
export const DEFAULT_SORT: SortMode = "recommended";

export const SORT_LABELS: Record<SortMode, string> = {
  recommended: "Recommended",
  name: "Name A–Z",
};

export function isSortMode(v: unknown): v is SortMode {
  return typeof v === "string" && (SORT_KEYS as readonly string[]).includes(v);
}

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
  // Derived and stored server-side (agentarea_registry.application.catalog_facets)
  // so browsing can filter, sort and count in SQL. Optional because the
  // single-item endpoints predate them.
  category?: string | null;
  featured?: boolean | null;
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
  // Connections only: MCP server or plain HTTP API. Null for every other type,
  // which holds one kind of thing.
  protocol: CatalogProtocol | null;
  // Logo chain + initials, resolved by <EntityMark> at render time.
  identity: EntityIdentity;
  featured: boolean; // hand-curated well-known entry (sorts first server-side)
  verified: boolean; // official vendor connection with confirmed OAuth
  installEntityId: string | null; // linked MCP spec id → existing create-from-spec page
  spec: RawSpec;
};

export function isCatalogType(v: unknown): v is CatalogType {
  return typeof v === "string" && (TYPE_KEYS as readonly string[]).includes(v);
}

/** A catalog tab from a URL value, accepting the tab's former name. */
export function toCatalogType(v: unknown): CatalogType | null {
  if (isCatalogType(v)) return v;
  return typeof v === "string" ? (LEGACY_TYPES[v] ?? null) : null;
}

export function isCatalogProtocol(v: unknown): v is CatalogProtocol {
  return typeof v === "string" && (PROTOCOL_KEYS as readonly string[]).includes(v);
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

// Normalize a model slug for tolerant matching: drop the provider prefix
// ("openai/gpt-4o-mini" → "gpt-4o-mini"), lowercase, strip non-alphanumerics.
export function normalizeModelSlug(s: string): string {
  const tail = s.includes("/") ? s.slice(s.lastIndexOf("/") + 1) : s;
  return tail.toLowerCase().replace(/[^a-z0-9]/g, "");
}

// Does a workspace model name plausibly satisfy a catalog "preferred" slug?
// Tolerant (substring either way) because catalog slugs are bare ("gpt-4o")
// while real instances are provider-prefixed/variant ("openai/gpt-4o-mini").
// Non-binding — it only drives a UI suggestion, never a backend choice.
export function modelNameMatchesPreferred(
  modelName: string,
  preferred: string
): boolean {
  const m = normalizeModelSlug(modelName);
  const p = normalizeModelSlug(preferred);
  if (!m || !p) return false;
  return m.includes(p) || p.includes(m);
}

// Only what can safely become an `<img src>`: an app-relative path or an
// http(s) URL. Catalog sources are external, and a `javascript:`/`data:` src
// is not something the gallery should hand to the browser.
function iconSrc(value: unknown): string | null {
  const s = str(value);
  if (!s) return null;
  if (s.startsWith("/")) return s;
  return /^https?:\/\//i.test(s) ? s : null;
}

// GitHub renders an owner's avatar at `github.com/<owner>.png`. Skills are
// published per repo and carry no artwork of their own, so the publisher's
// avatar is the only thing that tells two of them apart at a glance.
function githubOwnerAvatar(spec: RawSpec): string | null {
  const provenance = spec.provenance as RawSpec | undefined;
  const repo = provenance ? str(provenance.repo) : null;
  const owner =
    repo?.split("/")[0] ??
    str(spec.source_url)?.match(
      /^https?:\/\/(?:www\.)?github\.com\/([^/?#]+)/i
    )?.[1];
  return owner ? `https://github.com/${owner}.png?size=128` : null;
}

// Every logo the sources gave us, best first and deduplicated. MCP registry
// items keep the full upstream server object under spec.raw_spec, whose
// `icons` is a list of {src, mimeType}, and our curation adds a hosted
// fallback alongside it; other types may carry a flat icon/metadata.icon.
// A connection with no artwork at all still has an endpoint, and the service
// behind it serves a favicon.
function iconSources(
  type: CatalogType,
  spec: RawSpec,
  endpoint: string | null
): string[] {
  const raw = (spec.raw_spec as RawSpec | undefined) ?? spec;
  const meta = spec.metadata as RawSpec | undefined;
  const rawMeta = raw.metadata as RawSpec | undefined;

  const candidates = [
    spec.icon,
    spec.icon_url,
    meta?.icon,
    ...arr(raw.icons).map((icon) => icon.src),
    rawMeta?.["agentarea:logo_source_url"],
    type === "skills" ? githubOwnerAvatar(spec) : null,
    ...faviconSources(endpoint),
  ];

  const seen: string[] = [];
  for (const candidate of candidates) {
    const src = iconSrc(candidate);
    if (src && !seen.includes(src)) seen.push(src);
  }
  return seen;
}

// A catalog entry looks like whatever it is a catalog entry *of*: an MCP
// server, an HTTP API, an agent, a skill, a bundle. <EntityMark> walks the
// sources and drops to the initials, so no tile is ever a row of identical
// glyphs.
const ENTITY_KIND: Record<CatalogType, EntityKind> = {
  bundles: "project",
  agents: "agent",
  skills: "skill",
  connections: "mcp",
};

export function catalogIdentity(
  entry: Pick<CatalogEntry, "type" | "title" | "protocol" | "spec">
): EntityIdentity {
  // Where an MCP connection is reached, when it is reached over the network at
  // all (a command/docker server has no URL, and falls back to its name).
  const endpoint = entry.type === "connections" ? str(entry.spec.url) : null;
  return {
    kind:
      entry.protocol === "api" ? "client" : ENTITY_KIND[entry.type],
    sources: iconSources(entry.type, entry.spec, endpoint),
    initials: domainInitials(endpoint, entry.title),
  };
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
  const acronyms = new Set([
    "api",
    "csv",
    "docx",
    "html",
    "json",
    "mcp",
    "pdf",
    "pptx",
    "seo",
    "sql",
    "ui",
    "ux",
    "xlsx",
  ]);
  return (
    head
      .split(" ")
      .map((word) =>
        acronyms.has(word.toLowerCase())
          ? word.toUpperCase()
          : word.charAt(0).toUpperCase() + word.slice(1)
      )
      .join(" ") || name
  );
}

export function normalize(type: CatalogType, item: RegistryItem): CatalogEntry {
  const entry = describe(type, item);
  return { ...entry, identity: catalogIdentity(entry) };
}

// Everything about an entry except how it is depicted, which is derived from
// the rest (the title seeds the initials, the protocol picks the glyph).
function describe(
  type: CatalogType,
  item: RegistryItem
): Omit<CatalogEntry, "identity"> {
  const spec = item.spec || {};
  const tags = item.tags || [];
  // Only connections have a protocol; the backend's split is the same test.
  const protocol: CatalogProtocol | null =
    type !== "connections"
      ? null
      : str(spec.connection_type) === OPENAPI_CONNECTION_TYPE
        ? "api"
        : "mcp";
  // The server derives `category`/`featured` and browses by those exact values.
  // Re-deriving them here would risk a card sitting under a facet whose filter
  // never returns it, so the stored values win; the local derivation is only a
  // fallback for endpoints that don't carry them yet.
  const base = {
    id: item.id,
    type,
    description: item.description || "",
    tags,
    protocol,
    featured: item.featured ?? tags.includes(FEATURED_TAG),
    verified: false,
    installEntityId: item.installed_entity_id ?? null,
    spec,
  };
  const serverCategory = str(item.category);

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
    n("channels", "channel");
    n("automations", "automation");
    return {
      ...base,
      title: str(spec.display_name) || str(spec.name) || item.name,
      category: serverCategory ?? str(meta?.category),
      integrations: arr(spec.mcps)
        .map((m) => String(m.name ?? ""))
        .filter(Boolean),
      meta: counts,
    };
  }
  if (type === "agents") {
    // Catalog agents declare model *preferences* (slugs, priority order) — a hint
    // for the UI to suggest a model. The backend never binds a concrete model on
    // install.
    const models = strArr(spec.preferred_models);
    return {
      ...base,
      title: item.name,
      // Catalog agents carry domain tags (support, engineering, data…); the
      // first one is a sensible category.
      category: serverCategory ?? str(item.tags?.[0]),
      integrations: [],
      meta: models,
    };
  }
  if (type === "skills") {
    // Skills encode their category and source repo as "category:<x>" / "repo:<x>"
    // tags. Show the repo as the card fact (the "content" source_type is noise);
    // use it to strip the repo from the generated title too.
    const tagVal = (prefix: string) =>
      (item.tags ?? [])
        .find((t) => t.startsWith(prefix))
        ?.slice(prefix.length) ?? null;
    const repo = tagVal("repo:");
    const originalName = str(spec.original_name);
    return {
      ...base,
      title:
        str(spec.display_name) ??
        prettifySkillName(
          originalName ?? item.name,
          originalName ? null : repo
        ),
      category: serverCategory ?? tagVal("category:"),
      integrations: [],
      meta: repo ? [repo] : [],
    };
  }
  // Connections. Category comes from curated metadata when the source provides
  // it (agentarea:category); the transport (streamable-http, command, sse…) is
  // "how it connects", not a category, so we don't facet on it.
  const rawMeta = (spec.raw_spec as RawSpec | undefined)?.metadata as
    | RawSpec
    | undefined;
  const transport = str(spec.connection_type) ?? str(spec.transport) ?? "url";
  return {
    ...base,
    title: item.name,
    category: serverCategory ?? str(rawMeta?.["agentarea:category"]),
    verified: rawMeta?.["agentarea:oauth_status"] === "verified",
    integrations: [],
    // The protocol badge already says "HTTP API"; for an MCP server the
    // transport is the one fact the badge doesn't carry.
    meta: base.protocol === "api" ? [] : [transport],
  };
}

"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  BadgeCheck,
  Blocks,
  Bot,
  CheckCircle2,
  ChevronLeft,
  Clock,
  LayoutGrid,
  Loader2,
  Plug,
  Puzzle,
  Rows3,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { cn } from "@/lib/utils";

// ── Registry types ──────────────────────────────────────────────────────────
// One gallery for every catalog type. The look-and-feel is shared; the type is
// just a tab. Each raw registry_item is normalized to a single CatalogEntry so
// every card renders through the same component regardless of type.

type CatalogType = "bundles" | "agents" | "skills" | "mcp_servers";

const TYPES: { key: CatalogType; label: string; icon: LucideIcon }[] = [
  { key: "bundles", label: "Bundles", icon: Blocks },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "skills", label: "Skills", icon: Puzzle },
  { key: "mcp_servers", label: "Connections", icon: Plug },
];

const PAGE = 96;
const ALL = "__all__";

const TYPE_KEYS = ["bundles", "agents", "skills", "mcp_servers"] as const satisfies readonly CatalogType[];
const VIEW_KEYS = ["grid", "table"] as const;

type ViewMode = (typeof VIEW_KEYS)[number];

type LucideIcon = React.ComponentType<{ className?: string }>;

type RawSpec = Record<string, unknown>;
type RegistryItem = {
  id: string;
  name: string;
  description: string | null;
  version: string | null;
  tags: string[];
  spec: RawSpec;
  installed_entity_id?: string | null;
};
type Registry = { id: string; name: string; registry_type: string };

// Normalized shape every card/drawer renders from.
type CatalogEntry = {
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

const FEATURED_TAG = "featured";

// ── Data ──

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`/api/proxy/${path}`, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

async function fetchPage(type: CatalogType, offset: number): Promise<RegistryItem[]> {
  const registries = await getJSON<Registry[]>(
    `v1/registries/?registry_type=${type}&active_only=true`
  );
  // Most types have a single registry; sum a page across them for robustness.
  const lists = await Promise.all(
    registries.map((r) => getJSON<RegistryItem[]>(`v1/registries/${r.id}/items?limit=${PAGE}&offset=${offset}`))
  );
  return lists.flat();
}

// ── Normalization (per type → CatalogEntry) ──

function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}
function arr(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? (v as Record<string, unknown>[]) : [];
}

// Best-effort logo URL from whatever the source preserved. MCP registry items
// keep the full upstream server object under spec.raw_spec, whose `icons` is a
// list of {src, mimeType}. Other types may carry a flat icon/metadata.icon.
function extractIcon(spec: RawSpec): string | null {
  const raw = (spec.raw_spec as RawSpec | undefined) ?? spec;
  const icons = arr(raw.icons);
  if (icons.length > 0) {
    const src = str(icons[0].src);
    if (src) return src;
  }
  const meta = spec.metadata as RawSpec | undefined;
  return str(spec.icon) ?? str(spec.icon_url) ?? (meta ? str(meta.icon) : null);
}

function normalize(type: CatalogType, item: RegistryItem): CatalogEntry {
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
      title: item.name,
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

const TYPE_ICON: Record<CatalogType, LucideIcon> = {
  bundles: Blocks,
  agents: Bot,
  skills: Puzzle,
  mcp_servers: Plug,
};

// ── Component ──

export default function CatalogGallery() {
  // Catalog UI state lives in the URL (nuqs) so views are shareable/back-able.
  const [type, setType] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault("bundles")
  );
  const [entries, setEntries] = useState<CatalogEntry[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useQueryState("q", parseAsString.withDefault(""));
  const [category, setCategory] = useQueryState("category", parseAsString.withDefault(ALL));
  const [view, setView] = useQueryState(
    "view",
    parseAsStringLiteral(VIEW_KEYS).withDefault("grid")
  );
  const [itemId, setItemId] = useQueryState("item", parseAsString);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(
    async (t: CatalogType, off: number, append: boolean) => {
      append ? setMore(true) : setLoading(true);
      setError(null);
      try {
        const page = await fetchPage(t, off);
        const mapped = page.map((it) => normalize(t, it));
        setEntries((prev) => (append ? [...prev, ...mapped] : mapped));
        setOffset(off + page.length);
        // A short page means the server has nothing more — stop infinite scroll.
        setHasMore(page.length >= PAGE);
        setMore(false);
        setLoading(false);
        return page.length;
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
        setHasMore(false);
        setMore(false);
        setLoading(false);
        return 0;
      }
    },
    []
  );

  useEffect(() => {
    setEntries([]);
    setOffset(0);
    void load(type, 0, false);
  }, [type, load]);

  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of entries) {
      if (e.category) counts.set(e.category, (counts.get(e.category) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [entries]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return entries
      .filter((e) => {
        if (category !== ALL && e.category !== category) return false;
        if (q) {
          const hay = `${e.title} ${e.description} ${e.tags.join(" ")}`.toLowerCase();
          if (!hay.includes(q)) return false;
        }
        return true;
      })
      // Alphabetical by name, case-insensitive (so "monday.com"/"v0.dev" sit
      // where you'd expect, not after "Zapier").
      .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }, [entries, query, category]);

  // Infinite scroll: auto-load the next page when the sentinel nears the viewport.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore || more || loading) return;
    const io = new IntersectionObserver(
      (obs) => {
        if (obs[0]?.isIntersecting) void load(type, offset, true);
      },
      { rootMargin: "600px" }
    );
    io.observe(node);
    return () => io.disconnect();
  }, [hasMore, more, loading, type, offset, load]);

  // Selected item (from ?item=) resolved against what's loaded. When set, the
  // main column shows the detail in place — tabs + facets stay, so it feels
  // like browsing a marketplace rather than a full-page takeover.
  const active = itemId ? (entries.find((e) => e.id === itemId) ?? null) : null;

  return (
    <div className="space-y-4">
      {/* Type tabs — the primary axis */}
      <div className="flex flex-wrap gap-2 border-b border-border/60 pb-3">
        {TYPES.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              onClick={() => {
                void setType(t.key);
                void setCategory(ALL);
                void setItemId(null);
              }}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                type === t.key
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              <Icon className="h-4 w-4" />
              {t.label}
            </button>
          );
        })}
      </div>

      <div className="flex gap-6">
        {/* Facet sidebar — always reserved (fixed width) so the layout doesn't
            shift when categories arrive. Shows a skeleton while loading. */}
        <aside className="hidden w-52 shrink-0 lg:block">
          {loading ? (
            <FacetSkeleton />
          ) : categories.length > 0 ? (
            <FacetGroup
              label="Category"
              options={categories}
              selected={category}
              onSelect={(v) => {
                void setCategory(v);
                void setItemId(null);
              }}
            />
          ) : null}
        </aside>

        {/* Main */}
        <div className="min-w-0 flex-1 space-y-4">
          {active ? (
            <DetailView entry={active} onBack={() => void setItemId(null)} />
          ) : (
          <>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => void setQuery(e.target.value)}
                placeholder={`Search ${TYPES.find((t) => t.key === type)?.label.toLowerCase()}…`}
                className="pl-9"
              />
            </div>
            <ViewToggle view={view} onChange={(v) => void setView(v)} />
          </div>

          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}
          {loading && <GridSkeleton />}
          {!loading && filtered.length === 0 && !error && (
            <EmptyState title="Nothing here" detail="Try another type, clear filters, or search." />
          )}

          {!loading && filtered.length > 0 && (
            <>
              {view === "grid" ? (
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {filtered.map((e) => (
                    <CatalogCard key={e.id} entry={e} onOpen={() => void setItemId(e.id)} />
                  ))}
                </div>
              ) : (
                <CatalogTable entries={filtered} onOpen={(e) => void setItemId(e.id)} />
              )}

              {/* Infinite-scroll sentinel + manual fallback */}
              <div ref={sentinelRef} className="h-px" aria-hidden />
              {hasMore && (
                <div className="flex justify-center pt-2">
                  {more ? (
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  ) : (
                    <Button variant="outline" onClick={() => load(type, offset, true)}>
                      Load more
                    </Button>
                  )}
                </div>
              )}
            </>
          )}
          </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── View toggle (grid / table) ──

function ViewToggle({ view, onChange }: { view: ViewMode; onChange: (v: ViewMode) => void }) {
  const opts: { key: ViewMode; icon: LucideIcon; label: string }[] = [
    { key: "grid", icon: LayoutGrid, label: "Grid view" },
    { key: "table", icon: Rows3, label: "Table view" },
  ];
  return (
    <div className="flex shrink-0 rounded-md border border-border/60 p-0.5">
      {opts.map((o) => {
        const Icon = o.icon;
        return (
          <button
            key={o.key}
            type="button"
            title={o.label}
            aria-label={o.label}
            aria-pressed={view === o.key}
            onClick={() => onChange(o.key)}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded transition-colors",
              view === o.key
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="h-4 w-4" />
          </button>
        );
      })}
    </div>
  );
}

// ── Table view (compact, scannable; same click → drawer) ──

function CatalogTable({
  entries,
  onOpen,
}: {
  entries: CatalogEntry[];
  onOpen: (e: CatalogEntry) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <table className="w-full text-sm">
        <tbody>
          {entries.map((e) => {
            const TypeIcon = TYPE_ICON[e.type];
            return (
              <tr
                key={e.id}
                onClick={() => onOpen(e)}
                className="cursor-pointer border-b border-border/40 last:border-0 hover:bg-muted/40"
              >
                <td className="w-10 py-2 pl-3 pr-0">
                  {e.iconUrl ? (
                    <BrandLogo src={e.iconUrl} alt={e.title} fallback={TypeIcon} small />
                  ) : (
                    <span className="flex h-6 w-6 items-center justify-center rounded border border-border/60 bg-white dark:bg-zinc-800">
                      <TypeIcon className="h-3.5 w-3.5 text-zinc-400" />
                    </span>
                  )}
                </td>
                <td className="py-2 pl-2 pr-3 align-middle">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{e.title}</span>
                    {e.verified && (
                      <BadgeCheck className="h-3.5 w-3.5 shrink-0 text-blue-500" />
                    )}
                    {e.category && (
                      <Badge variant="light" size="sm" className="capitalize">
                        {e.category}
                      </Badge>
                    )}
                  </div>
                </td>
                <td className="hidden max-w-0 truncate py-2 pr-4 text-xs text-muted-foreground md:table-cell">
                  {e.description}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Facet group ──

function FacetSkeleton() {
  return (
    <div className="mb-6">
      <div className="mb-2 h-3 w-20 rounded bg-muted/60" />
      <div className="space-y-1">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-7 animate-pulse rounded-md bg-muted/40" />
        ))}
      </div>
    </div>
  );
}

function FacetGroup({
  label,
  options,
  selected,
  onSelect,
}: {
  label: string;
  options: [string, number][];
  selected: string;
  onSelect: (v: string) => void;
}) {
  const rows: [string, number | null][] = [[ALL, null], ...options];
  return (
    <div className="mb-6">
      <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="space-y-0.5">
        {rows.map(([value, count]) => (
          <button
            key={value}
            onClick={() => onSelect(value)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
              selected === value
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted/50"
            )}
          >
            <span className="min-w-0 flex-1 truncate text-left capitalize">
              {value === ALL ? "All" : value}
            </span>
            {count !== null && (
              <span className="text-[10px] tabular-nums text-muted-foreground">{count}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Card (uniform across every type) ──

// Upstream logo with a graceful fallback to the type glyph if the image 404s
// or the host blocks hotlinking.
function BrandLogo({
  src,
  alt,
  fallback: Fallback,
  small = false,
}: {
  src: string;
  alt: string;
  fallback: LucideIcon;
  small?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span
        className={cn(
          "flex items-center justify-center rounded-lg border border-border/60 bg-white shadow-sm dark:bg-zinc-800",
          small ? "h-6 w-6" : "h-9 w-9"
        )}
      >
        <Fallback className={cn("text-zinc-400", small ? "h-3.5 w-3.5" : "h-4 w-4")} />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "flex items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-white shadow-sm dark:bg-zinc-800",
        small ? "h-6 w-6 p-0.5" : "h-10 w-10 p-1.5"
      )}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="h-full w-full object-contain"
        onError={() => setFailed(true)}
      />
    </span>
  );
}

function CatalogCard({ entry, onOpen }: { entry: CatalogEntry; onOpen: () => void }) {
  const TypeIcon = TYPE_ICON[entry.type];
  return (
    <button
      onClick={onOpen}
      className="group flex flex-col overflow-hidden rounded-lg border border-border/60 bg-white text-left transition-shadow hover:shadow-md dark:border-zinc-700/60 dark:bg-zinc-900"
    >
      <div className="relative flex h-24 items-center justify-center gap-1.5 border-b border-border/40 bg-[radial-gradient(circle,theme(colors.zinc.200)_1px,transparent_1px)] [background-size:12px_12px] dark:bg-[radial-gradient(circle,theme(colors.zinc.800)_1px,transparent_1px)]">
        {entry.verified ? (
          <span className="absolute left-2 top-2">
            <Badge variant="blue" size="sm" className="gap-1">
              <BadgeCheck className="h-3 w-3" />
              Verified
            </Badge>
          </span>
        ) : entry.featured ? (
          <span className="absolute left-2 top-2">
            <Badge variant="blue" size="sm" className="gap-1">
              <Star className="h-3 w-3 fill-current" />
              Featured
            </Badge>
          </span>
        ) : null}
        {entry.iconUrl ? (
          <BrandLogo src={entry.iconUrl} alt={entry.title} fallback={TypeIcon} />
        ) : entry.integrations.length > 0 ? (
          entry.integrations.slice(0, 4).map((name) => (
            <span
              key={name}
              title={name}
              className="flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 bg-white text-xs font-bold uppercase text-zinc-500 shadow-sm dark:bg-zinc-800"
            >
              {name.slice(0, 1)}
            </span>
          ))
        ) : (
          <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border/60 bg-white shadow-sm dark:bg-zinc-800">
            <TypeIcon className="h-4 w-4 text-zinc-400" />
          </span>
        )}
        <span className="absolute right-2 top-2 opacity-0 transition-opacity group-hover:opacity-100">
          <Badge variant="default" size="sm">
            View
          </Badge>
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold">{entry.title}</span>
          {entry.category && (
            <Badge variant="light" size="sm" className="capitalize">
              {entry.category}
            </Badge>
          )}
        </div>
        <p className="line-clamp-2 text-xs text-muted-foreground">{entry.description}</p>
        {entry.meta.length > 0 && (
          <div className="mt-auto truncate pt-2 text-[11px] text-muted-foreground">
            {entry.meta.join(" · ")}
          </div>
        )}
      </div>
    </button>
  );
}

// ── In-page detail view (look first; Connect runs the real setup) ──

type InstallState =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "connecting" }
  | { phase: "needs_config" }
  | { phase: "done"; created: number }
  | { phase: "error"; message: string };

// Setup tiers carried in curated metadata (see the catalog source). Drives what
// the Connect action asks for before it can add the connection.
type SetupTier =
  | "one_click"
  | "oauth"
  | "needs_oauth_app"
  | "needs_tenant_config"
  | "unverified";

function DetailView({ entry, onBack }: { entry: CatalogEntry; onBack: () => void }) {
  const [state, setState] = useState<InstallState>({ phase: "idle" });

  const spec = entry.spec;
  const rawMeta = (spec.raw_spec as RawSpec | undefined)?.metadata as RawSpec | undefined;
  const tier = (str(rawMeta?.["agentarea:setup_tier"]) ?? "unverified") as SetupTier;
  const TypeIcon = TYPE_ICON[entry.type];

  // Setup reuses the existing "create instance from spec" page — the catalog
  // never configures inline. Each catalog connection links to an MCP spec.
  const connectHref = entry.installEntityId
    ? `/mcp-servers/create/${entry.installEntityId}`
    : "/mcp-servers/add";

  useEffect(() => {
    // Reset only when the selected item changes.
    setState({ phase: "idle" });
  }, [entry.id]);

  async function installBundle() {
    const required = arr(spec.setup).filter(
      (f) => f.required && (f.default === undefined || f.default === null || f.default === "")
    );
    if (required.length > 0) {
      setState({ phase: "needs_config" });
      return;
    }
    setState({ phase: "loading" });
    try {
      const aRes = await fetch(`/api/proxy/v1/bundles/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: JSON.stringify(spec) }),
      });
      const preview = await aRes.json();
      if (!aRes.ok) throw new Error(preview?.detail ?? "Analyze failed");
      const setupValues: Record<string, unknown> = {};
      for (const f of preview.setup ?? []) {
        if (f.default !== undefined && f.default !== null) setupValues[f.key] = f.default;
      }
      const iRes = await fetch(`/api/proxy/v1/bundles/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bundle: preview.bundle, setup_values: setupValues }),
      });
      const result = await iRes.json();
      if (!iRes.ok) throw new Error(result?.detail?.message ?? result?.detail ?? "Install failed");
      setState({ phase: "done", created: (result.entities ?? []).length });
    } catch (e) {
      setState({ phase: "error", message: e instanceof Error ? e.message : "Install failed" });
    }
  }

  return (
    <div className="space-y-6">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to catalog
      </button>

      <div className="flex items-start gap-4">
        {entry.iconUrl ? (
          <BrandLogo src={entry.iconUrl} alt={entry.title} fallback={TypeIcon} />
        ) : (
          <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/60 bg-white shadow-sm dark:bg-zinc-800">
            <TypeIcon className="h-5 w-5 text-zinc-400" />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold">{entry.title}</h2>
            {entry.verified && (
              <Badge variant="blue" size="sm" className="gap-1">
                <BadgeCheck className="h-3 w-3" />
                Verified
              </Badge>
            )}
            {entry.category && (
              <Badge variant="light" size="sm" className="capitalize">
                {entry.category}
              </Badge>
            )}
          </div>
          {entry.description && (
            <p className="mt-1 text-sm text-muted-foreground">{entry.description}</p>
          )}
        </div>
      </div>

      <div className="max-w-2xl space-y-5">
          {entry.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {entry.tags.slice(0, 12).map((t) => (
                <Badge key={t} variant="light" size="sm">
                  {t}
                </Badge>
              ))}
            </div>
          )}

          {entry.type === "bundles" && (
            <>
              <Inside icon={Bot} label="Agents" rows={arr(spec.agents).map((a) => String(a.name ?? a.key))} />
              <Inside icon={Puzzle} label="Skills" rows={arr(spec.skills).map((s) => String(s.name ?? s.key))} />
              <Inside
                icon={Plug}
                label="Connections"
                rows={arr(spec.mcps).map((m) => String(m.name ?? m.key))}
                hint="Connected via OAuth after install"
              />
              <Inside
                icon={Clock}
                label="Automations"
                rows={arr(spec.automations).map((a) => {
                  const kind = str(a.type) ?? str(a.trigger) ?? str(a.kind) ?? str(a.schedule);
                  const name = String(a.name ?? a.key ?? "automation");
                  return kind ? `${name} · ${kind}` : name;
                })}
                hint="Imported disabled — enable when ready"
              />
              <Inside
                icon={ShieldCheck}
                label="Policies"
                rows={arr(spec.policies).map((p) => {
                  const msg = str(p.message);
                  if (msg) return msg;
                  const effect = str(p.effect);
                  const target = str(p.target);
                  return effect && target ? `${effect} · ${target}` : String(p.key ?? "policy");
                })}
                hint="Govern this bundle at runtime"
              />
            </>
          )}
          {entry.type === "agents" && (
            <Inside icon={Bot} label="Model" rows={entry.meta} />
          )}
          {entry.type === "mcp_servers" && <ConnectionSetup tier={tier} />}
          {(entry.type === "agents" || entry.type === "skills") && (
            <p className="rounded-lg border border-dashed border-border/60 px-4 py-3 text-xs text-muted-foreground">
              Adding {entry.type === "agents" ? "a catalog agent" : "a skill"} to your workspace is
              coming next.
            </p>
          )}

          {state.phase === "needs_config" && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30">
              Needs configuration — open it in the{" "}
              <Link href="/bundles/import" className="underline">
                importer
              </Link>
              .
            </div>
          )}
          {state.phase === "error" && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              {state.message}
            </div>
          )}
          {state.phase === "done" && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              Installed — {state.created} entities created.
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-2">
            {entry.type === "bundles" ? (
              state.phase === "done" ? (
                <Button asChild>
                  <Link href="/agents">Go to Agents</Link>
                </Button>
              ) : (
                <Button onClick={installBundle} isLoading={state.phase === "loading"}>
                  {state.phase !== "loading" && (
                    <>
                      <Sparkles className="h-4 w-4" />
                      Use this bundle
                    </>
                  )}
                </Button>
              )
            ) : entry.type === "mcp_servers" ? (
              <Button asChild>
                <Link href={connectHref}>
                  <Plug className="h-4 w-4" />
                  Connect
                </Link>
              </Button>
            ) : (
              <Button variant="outline" disabled>
                Add to workspace (soon)
              </Button>
            )}
          </div>
        </div>
    </div>
  );
}

function ConnectionSetup({ tier }: { tier: SetupTier }) {
  const COPY: Record<SetupTier, { icon: LucideIcon; title: string; detail: string }> = {
    one_click: {
      icon: BadgeCheck,
      title: "One-click connect",
      detail: "Authorize access in the next step — nothing to set up.",
    },
    oauth: {
      icon: BadgeCheck,
      title: "Connect with OAuth",
      detail: "You'll authorize access in the next step.",
    },
    needs_oauth_app: {
      icon: AlertTriangle,
      title: "Needs an OAuth app",
      detail:
        "This vendor requires a one-time OAuth app (client ID/secret). You can add it now and finish auth on the connection page.",
    },
    needs_tenant_config: {
      icon: Plug,
      title: "Enter your workspace URL",
      detail: "This connection is hosted in your own tenant — paste your full MCP URL.",
    },
    unverified: {
      icon: AlertTriangle,
      title: "Not verified yet",
      detail: "We'll try to connect; you may need to finish setup manually.",
    },
  };
  const c = COPY[tier];
  const Icon = c.icon;
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{c.title}</p>
          <p className="text-xs text-muted-foreground">{c.detail}</p>
        </div>
      </div>
    </div>
  );
}

function Inside({
  icon: Icon,
  label,
  rows,
  hint,
}: {
  icon: LucideIcon;
  label: string;
  rows: string[];
  hint?: string;
}) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
        <span className="tabular-nums">({rows.length})</span>
      </div>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r} className="truncate rounded bg-muted/50 px-2 py-1 text-sm">
            {r}
          </li>
        ))}
      </ul>
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

// ── Misc ──

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-48 animate-pulse rounded-lg border border-border/60 bg-muted/40" />
      ))}
    </div>
  );
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border/60 px-6 py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}

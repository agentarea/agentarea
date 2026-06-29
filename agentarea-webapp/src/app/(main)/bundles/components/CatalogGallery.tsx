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
  ExternalLink,
  FileText,
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
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { Streamdown } from "streamdown";
import { AgentAvatar } from "@/components/AgentAvatar";
import ModelBadge from "@/components/ui/model-badge";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { cn } from "@/lib/utils";
import {
  ALL,
  FEATURED_TAG,
  PAGE,
  TYPE_KEYS,
  arr,
  normalize,
  str,
  strArr,
  type CatalogEntry,
  type CatalogType,
  type RawSpec,
  type Registry,
  type RegistryItem,
} from "./catalog-data";

// ── Registry types ──────────────────────────────────────────────────────────
// One gallery for every catalog type. The look-and-feel is shared; the type is
// just a tab. Each raw registry_item is normalized to a single CatalogEntry
// (see catalog-data.ts, shared with the SSR page) so every card renders through
// the same component regardless of type.

type LucideIcon = React.ComponentType<{ className?: string }>;

const TYPES: { key: CatalogType; label: string; icon: LucideIcon }[] = [
  { key: "bundles", label: "Bundles", icon: Blocks },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "skills", label: "Skills", icon: Puzzle },
  { key: "mcp_servers", label: "Connections", icon: Plug },
];

const VIEW_KEYS = ["grid", "table"] as const;

type ViewMode = (typeof VIEW_KEYS)[number];

// ── Data (client-side, for infinite-scroll "load more" only) ──
// The first page is server-rendered (see explore/page.tsx); these helpers only
// run for offset > 0 appends, so they can never race the initial paint.

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

const TYPE_ICON: Record<CatalogType, LucideIcon> = {
  bundles: Blocks,
  agents: Bot,
  skills: Puzzle,
  mcp_servers: Plug,
};

// ── Component ──

type CatalogGalleryProps = {
  initialType: CatalogType;
  initialEntries: CatalogEntry[];
  initialHasMore: boolean;
  initialError?: string | null;
};

export default function CatalogGallery({
  initialType,
  initialEntries,
  initialHasMore,
  initialError = null,
}: CatalogGalleryProps) {
  // Catalog UI state lives in the URL (nuqs) so views are shareable/back-able.
  // `type` uses shallow:false so switching tabs re-runs the Server Component
  // (explore/page.tsx) and re-fetches the first page server-side. Combined with
  // `key={type}` on this component, every type view starts from fresh SSR data —
  // there is no client fetch on mount and no stale-response race across types.
  const [type, setType] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault(initialType).withOptions({
      shallow: false,
    })
  );
  // Seeded from the server-rendered first page (no initial client fetch / flash).
  const [entries, setEntries] = useState<CatalogEntry[]>(initialEntries);
  const [offset, setOffset] = useState(initialEntries.length);
  const [loading, setLoading] = useState(false);
  const [more, setMore] = useState(false);
  const [hasMore, setHasMore] = useState(initialHasMore);
  const [error, setError] = useState<string | null>(initialError);

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
      <table className="w-full table-fixed text-sm">
        <colgroup>
          <col className="w-10" />
          <col className="md:w-[42%]" />
          <col className="hidden md:table-column" />
        </colgroup>
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
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 truncate font-medium">{e.title}</span>
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

  // Machine tags ("category:x", "repo:y", "featured"…) are provenance, not
  // topical labels — keep them out of the chip row (surfaced elsewhere instead).
  // Bundle capabilities get their own labeled row, so drop them here too.
  const capabilitySet = new Set(bundleCapabilities(spec));
  const topicalTags = entry.tags.filter(
    (t) => !t.includes(":") && t !== FEATURED_TAG && !capabilitySet.has(t)
  );

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

  async function installAgent() {
    setState({ phase: "loading" });
    try {
      // entry.id is the registry_item id; the endpoint forks a tenant copy
      // (copy-on-write) and is idempotent if already installed.
      const iRes = await fetch(`/api/proxy/v1/agents/${entry.id}/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const result = await iRes.json();
      if (!iRes.ok)
        throw new Error(result?.detail?.message ?? result?.detail ?? "Install failed");
      setState({ phase: "done", created: 1 });
    } catch (e) {
      setState({ phase: "error", message: e instanceof Error ? e.message : "Install failed" });
    }
  }

  const installing = state.phase === "loading";
  // Skills use the dedicated <AddSkillToAgent> control (agent picker + install),
  // so they're handled outside this generic install map.
  const installable: Record<CatalogEntry["type"], (() => void) | null> = {
    bundles: installBundle,
    agents: installAgent,
    skills: null,
    mcp_servers: null,
  };

  return (
    <div className="max-w-2xl space-y-8">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to catalog
      </button>

      {/* header — icon, title/badges, description, primary action */}
      <div className="flex flex-col gap-4 md:flex-row md:items-start">
        <div className="flex min-w-0 flex-1 items-start gap-4">
          {entry.iconUrl ? (
            <BrandLogo src={entry.iconUrl} alt={entry.title} fallback={TypeIcon} />
          ) : (
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-white shadow-sm dark:bg-zinc-800">
              <TypeIcon className="h-5 w-5 text-zinc-400" />
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold tracking-tight">{entry.title}</h2>
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
              <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
                {entry.description}
              </p>
            )}
          </div>
        </div>
        <CatalogActionSlot>
          {entry.type === "skills" ? (
            <AddSkillToAgent skillId={entry.id} />
          ) : state.phase === "done" ? (
            <Button asChild variant="outline">
              <Link href="/agents">Go to Agents</Link>
            </Button>
          ) : entry.type === "mcp_servers" ? (
            <StartAgentButton asChild size="xs">
              <Link href={connectHref}>
                Connect
              </Link>
            </StartAgentButton>
          ) : (
            <StartAgentButton
              size="xs"
              onClick={() => installable[entry.type]?.()}
              isLoading={installing}
            >
              {entry.type === "bundles" ? "Use this bundle" : "Add to workspace"}
            </StartAgentButton>
          )}
        </CatalogActionSlot>
      </div>

      {/* install feedback */}
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
          {entry.type === "agents"
            ? "Added to your workspace — it's now an editable copy you own."
            : `Installed — ${state.created} entities created.`}
        </div>
      )}

      {topicalTags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {topicalTags.slice(0, 12).map((t) => (
            <Badge key={t} variant="light" size="sm">
              {t}
            </Badge>
          ))}
        </div>
      )}

      {/* details */}
      <div className="space-y-5 border-t border-border/60 pt-6">
        {entry.type === "bundles" && <BundleContents spec={spec} />}
        {entry.type === "agents" && (
          <Inside
            icon={Bot}
            label="Preferred models"
            rows={entry.meta}
            hint="Suggested models — pick one for this agent after adding it."
          />
        )}
        {entry.type === "mcp_servers" && <ConnectionSetup tier={tier} />}
        {entry.type === "skills" && (
          <>
            <SkillContent
              skillId={entry.id}
              sourceType={str(spec.source_type) ?? "content"}
              sourceUrl={str(spec.source_url)}
            />
            <SkillFacts entry={entry} />
          </>
        )}
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

// ── Bundle contents (rich breakdown of what's inside a bundle) ──

// Each entity in a bundle carries far more than a name: agents have an
// instruction, a model, and the skills/connections they wire up; skills carry a
// source and a content preview; connections carry a transport and the secrets
// they bind. The detail view surfaces all of it so you can judge a bundle
// before installing — not just count its parts. Everything is referenced by
// in-bundle `key` (portable; ids are resolved on install), so we resolve those
// keys to display names against the bundle's own entity lists.

// Presentation capabilities a bundle advertises ("interactive", "write"…),
// carried in metadata — surfaced as their own labeled row, not loose tags.
function bundleCapabilities(spec: RawSpec): string[] {
  return strArr((spec.metadata as RawSpec | undefined)?.capabilities);
}

// Display name for an in-bundle reference key (e.g. an agent's skill/mcp key).
function bundleRefName(items: Record<string, unknown>[], key: string): string {
  const found = items.find((i) => str(i.key) === key);
  return found ? String(found.name ?? key) : key;
}

// Models are literal ids ("gpt-4o") or "${setup.x}" placeholders. Resolve the
// placeholder to the setup field's default so the card shows a real model name
// instead of a raw template; hide it when nothing concrete is known.
function resolveBundleModel(
  model: string | null,
  setup: Record<string, unknown>[]
): string | null {
  if (!model) return null;
  const ref = model.match(/^\$\{setup\.([a-zA-Z0-9_]+)\}$/);
  if (!ref) return model;
  const field = setup.find((f) => str(f.key) === ref[1]);
  return field ? str(field.default) : null;
}

// First meaningful line of a SKILL.md body, with the leading "# Heading" (which
// just repeats the skill name) dropped.
function skillPreview(content: string | null): string | null {
  if (!content) return null;
  const body = content
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.length > 0 && !l.startsWith("#"));
  return body ?? null;
}

function BundleSection({
  icon: Icon,
  label,
  count,
  hint,
  children,
}: {
  icon: LucideIcon;
  label: string;
  count: number;
  hint?: string;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
        <span className="tabular-nums">({count})</span>
      </div>
      <div className="space-y-2">{children}</div>
      {hint && <p className="mt-1.5 text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

// A small icon+text chip used to show an agent's wired skills/connections.
function RefChip({ icon: Icon, label }: { icon: LucideIcon; label: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-md border border-border/60 bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground">
      <Icon className="h-3 w-3 shrink-0" />
      <span className="truncate">{label}</span>
    </span>
  );
}

function BundleContents({ spec }: { spec: RawSpec }) {
  const agents = arr(spec.agents);
  const skills = arr(spec.skills);
  const mcps = arr(spec.mcps);
  const setup = arr(spec.setup);
  const automations = arr(spec.automations);
  const policies = arr(spec.policies);
  const capabilities = bundleCapabilities(spec);

  const total =
    agents.length +
    skills.length +
    mcps.length +
    automations.length +
    policies.length +
    capabilities.length;
  if (total === 0) return null;

  return (
    <>
      {capabilities.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Sparkles className="h-3.5 w-3.5" />
            Capabilities
          </div>
          <div className="flex flex-wrap gap-1.5">
            {capabilities.map((c) => (
              <Badge key={c} variant="light" size="sm" className="gap-1 capitalize">
                <Sparkles className="h-3 w-3" />
                {c.replace(/[-_]+/g, " ")}
              </Badge>
            ))}
          </div>
        </div>
      )}

      <BundleSection icon={Bot} label="Agents" count={agents.length}>
        {agents.map((a, i) => {
          const usesSkills = strArr(a.skills).map((k) => bundleRefName(skills, k));
          const usesMcps = strArr(a.mcps).map((k) => bundleRefName(mcps, k));
          const model = resolveBundleModel(str(a.model), setup);
          const instruction = str(a.instruction);
          return (
            <div
              key={str(a.key) ?? i}
              className="rounded-lg border border-border/60 bg-muted/20 p-3"
            >
              <div className="flex items-center gap-2">
                <AgentAvatar
                  agent={{ id: String(a.key ?? a.name ?? i), name: str(a.name) }}
                  size="sm"
                />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {String(a.name ?? a.key)}
                </span>
                {model && (
                  <ModelBadge modelDisplayName={model} size="sm" className="shrink-0" />
                )}
              </div>
              {instruction && (
                <p className="mt-2 line-clamp-3 whitespace-pre-line text-xs leading-relaxed text-muted-foreground">
                  {instruction}
                </p>
              )}
              {(usesSkills.length > 0 || usesMcps.length > 0) && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {usesSkills.map((s) => (
                    <RefChip key={`s-${s}`} icon={Puzzle} label={s} />
                  ))}
                  {usesMcps.map((m) => (
                    <RefChip key={`m-${m}`} icon={Plug} label={m} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </BundleSection>

      <BundleSection icon={Puzzle} label="Skills" count={skills.length}>
        {skills.map((s, i) => {
          const source = str(s.source_type) ?? "content";
          const preview =
            source === "github" ? str(s.source_url) : skillPreview(str(s.content));
          return (
            <div
              key={str(s.key) ?? i}
              className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {String(s.name ?? s.key)}
                </span>
                <Badge variant="light" size="sm" className="shrink-0">
                  {source}
                </Badge>
              </div>
              {preview && (
                <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{preview}</p>
              )}
            </div>
          );
        })}
      </BundleSection>

      <BundleSection
        icon={Plug}
        label="Connections"
        count={mcps.length}
        hint="Connected via OAuth or your credentials after install"
      >
        {mcps.map((m, i) => {
          const transport = str((m.json_spec as RawSpec | undefined)?.type);
          const binds = Object.keys(
            (m.bindings as Record<string, unknown> | undefined) ?? {}
          );
          return (
            <div
              key={str(m.key) ?? i}
              className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border/60 bg-white dark:bg-zinc-800">
                  <Plug className="h-3.5 w-3.5 text-zinc-400" />
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {String(m.name ?? m.key)}
                </span>
                {transport && (
                  <Badge variant="light" size="sm" className="shrink-0">
                    {transport}
                  </Badge>
                )}
              </div>
              {binds.length > 0 && (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Requires: {binds.join(", ")}
                </p>
              )}
            </div>
          );
        })}
      </BundleSection>

      <Inside
        icon={Clock}
        label="Automations"
        rows={automations.map((a) => {
          const kind = str(a.type) ?? str(a.trigger) ?? str(a.kind) ?? str(a.cron);
          const name = String(a.name ?? a.key ?? "automation");
          return kind ? `${name} · ${kind}` : name;
        })}
        hint="Imported disabled — enable when ready"
      />
      <Inside
        icon={ShieldCheck}
        label="Policies"
        rows={policies.map((p) => {
          const msg = str(p.message);
          if (msg) return msg;
          const effect = str(p.effect);
          const target = str(p.target);
          return effect && target ? `${effect} · ${target}` : String(p.key ?? "policy");
        })}
        hint="Govern this bundle at runtime"
      />
    </>
  );
}

type AgentLite = { id: string; name: string };

// Primary action for a catalog skill: attach it to an agent. A workspace skill
// that isn't attached to any agent does nothing, so the high-intent path is
// "add to agent" — fork the catalog skill into the workspace (copy-on-write,
// idempotent) and merge it into the chosen agent's skill set. "Add to
// workspace" stays as a quiet secondary for the library case.
function AddSkillToAgent({ skillId }: { skillId: string }) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentLite[] | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ label: string; href: string } | null>(null);

  // Lazy-load the workspace agents the first time the picker opens.
  useEffect(() => {
    if (!open || agents !== null) return;
    let active = true;
    fetch("/api/proxy/v1/agents", { headers: { Accept: "application/json" } })
      .then((r) => r.json())
      .then(
        (d) =>
          active &&
          setAgents(
            Array.isArray(d) ? d.map((a) => ({ id: String(a.id), name: String(a.name) })) : []
          )
      )
      .catch(() => active && setAgents([]));
    return () => {
      active = false;
    };
  }, [open, agents]);

  // Materialize the catalog skill into the workspace; returns the tenant id.
  async function fork(): Promise<string> {
    const r = await fetch(`/api/proxy/v1/skills/${skillId}/install`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d?.detail?.message ?? d?.detail ?? "Install failed");
    return String(d.id);
  }

  async function addToWorkspace() {
    setPhase("loading");
    try {
      await fork();
      setResult({ label: "Go to Skills", href: "/skills" });
      setPhase("done");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Install failed");
      setPhase("error");
    }
  }

  async function addToAgent(agent: AgentLite) {
    setOpen(false);
    setPhase("loading");
    try {
      const tenantId = await fork();
      // set_skills replaces the whole set, so merge with the agent's current ones.
      const aRes = await fetch(`/api/proxy/v1/agents/${agent.id}`, {
        headers: { Accept: "application/json" },
      });
      const a = await aRes.json();
      if (!aRes.ok) throw new Error(a?.detail ?? "Could not load agent");
      const current = arr(a.skills)
        .map((s) => str(s.id))
        .filter((id): id is string => Boolean(id));
      const skill_ids = Array.from(new Set([...current, tenantId]));
      const pRes = await fetch(`/api/proxy/v1/agents/${agent.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_ids }),
      });
      const p = await pRes.json();
      if (!pRes.ok) throw new Error(p?.detail?.message ?? p?.detail ?? "Could not attach skill");
      setResult({ label: `Open ${agent.name}`, href: `/agents/${agent.id}` });
      setPhase("done");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not attach skill");
      setPhase("error");
    }
  }

  if (phase === "done" && result) {
    return (
      <div className="flex flex-col items-start gap-1.5 md:items-end">
        <span className="flex items-center gap-1.5 text-sm font-medium text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="h-4 w-4" />
          Added
        </span>
        <Button asChild variant="outline" size="sm">
          <Link href={result.href}>{result.label}</Link>
        </Button>
      </div>
    );
  }

  const loading = phase === "loading";
  return (
    <div className="flex w-full flex-col items-start gap-1.5 md:items-end">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <StartAgentButton size="xs" isLoading={loading}>
            Add to agent
          </StartAgentButton>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-64 p-0">
          <Command>
            <CommandInput placeholder="Search agents…" />
            <CommandList>
              {agents === null ? (
                <div className="flex items-center justify-center py-6 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Loading…
                </div>
              ) : (
                <>
                  <CommandEmpty>
                    <div className="space-y-1.5 py-3 text-center text-sm text-muted-foreground">
                      <p>No agents yet.</p>
                      <Link href="/agents/create" className="block underline">
                        Create an agent
                      </Link>
                    </div>
                  </CommandEmpty>
                  <CommandGroup>
                    {agents.map((a) => (
                      <CommandItem key={a.id} value={a.name} onSelect={() => addToAgent(a)}>
                        <Bot className="mr-2 h-4 w-4 text-muted-foreground" />
                        <span className="truncate">{a.name}</span>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </>
              )}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <StartAgentButton
        type="button"
        size="xs"
        light
        onClick={addToWorkspace}
        disabled={loading}
        className="w-full"
      >
        Add to workspace
      </StartAgentButton>
      {phase === "error" && (
        <span className="max-w-[15rem] text-xs text-red-600 md:text-right dark:text-red-400">
          {message}
        </span>
      )}
    </div>
  );
}

function CatalogActionSlot({ children }: { children: React.ReactNode }) {
  return (
    <div className="w-full pl-[60px] md:ml-auto md:max-w-[210px] md:pl-0">
      {children}
    </div>
  );
}

type SkillFile = { path: string; size: number; url?: string | null };
type FileBody =
  | { kind: "md"; value: string }
  | { kind: "text"; value: string }
  | { kind: "link"; value: string };

// Extensions we can safely preview inline as text. Anything else gets an
// "open" link to its presigned URL instead of a garbled inline dump.
const TEXT_EXT = new Set([
  "md", "markdown", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml",
  "yml", "sh", "bash", "toml", "ini", "cfg", "csv", "html", "css", "xml",
  "sql", "env",
]);

function isTextFile(path: string): boolean {
  return TEXT_EXT.has(path.split(".").pop()?.toLowerCase() ?? "");
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// Strip YAML frontmatter (name/description — already shown in the header) from
// a SKILL.md body before rendering, matching the installed-skill viewer.
function skillBody(content: string): string {
  const m = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
  return (m ? m[2] : content).trim();
}

// Skill contents. The catalog item id resolves on the backend to either a
// tenant skill or a read-only catalog projection (see SkillService
// `get_with_catalog`), so the existing skill-file endpoints serve
// not-yet-installed catalog skills too:
//   GET /v1/skills/{id}/files        → the file tree (a single synthetic
//                                      SKILL.md for content skills; the real
//                                      S3 tree for multi-file packages)
//   GET /v1/skills/{id}/content      → the SKILL.md markdown
//   GET /v1/skills/{id}/files/{path} → a presigned URL to any package file
// We list the tree, render SKILL.md inline, and lazily load other text files on
// click — falling back to an "open" link when a file can't be previewed inline.
function SkillContent({
  skillId,
  sourceType,
  sourceUrl,
}: {
  skillId: string;
  sourceType: string;
  sourceUrl: string | null;
}) {
  const [files, setFiles] = useState<SkillFile[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [bodies, setBodies] = useState<Record<string, FileBody>>({});
  const [error, setError] = useState<string | null>(null);
  const requested = useRef<Set<string>>(new Set());

  // Load the file list once. A GitHub-sourced skill has no inlined files in the
  // catalog (they're fetched on install), so we skip straight to a source link.
  useEffect(() => {
    if (sourceType === "github") return;
    let active = true;
    getJSON<{ files: SkillFile[] }>(`v1/skills/${skillId}/files`)
      .then((d) => {
        if (!active) return;
        const fs = Array.isArray(d.files) ? d.files : [];
        setFiles(fs);
        const def = fs.find((f) => f.path.toLowerCase() === "skill.md") ?? fs[0] ?? null;
        setSelected(def?.path ?? null);
      })
      .catch(() => {
        if (!active) return;
        setFiles([]);
        setError("Could not load skill files.");
      });
    return () => {
      active = false;
    };
  }, [skillId, sourceType]);

  // Lazily load the selected file's body. SKILL.md comes from /content; other
  // files resolve to a presigned URL we then fetch (text) or link to.
  useEffect(() => {
    if (!selected || bodies[selected] || requested.current.has(selected)) return;
    requested.current.add(selected);
    let active = true;
    void (async () => {
      try {
        if (selected.toLowerCase() === "skill.md") {
          const d = await getJSON<{ content: string }>(`v1/skills/${skillId}/content`);
          if (active)
            setBodies((b) => ({
              ...b,
              [selected]: { kind: "md", value: skillBody(d.content || "") },
            }));
          return;
        }
        const { url } = await getJSON<{ url: string }>(
          `v1/skills/${skillId}/files/${encodeURI(selected)}?redirect=false`
        );
        if (isTextFile(selected)) {
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error();
            const text = await res.text();
            if (active) setBodies((b) => ({ ...b, [selected]: { kind: "text", value: text } }));
            return;
          } catch {
            // Cross-origin / unreadable — fall through to a plain open link.
          }
        }
        if (active) setBodies((b) => ({ ...b, [selected]: { kind: "link", value: url } }));
      } catch {
        if (active) setBodies((b) => ({ ...b, [selected]: { kind: "link", value: "" } }));
      }
    })();
    return () => {
      active = false;
    };
  }, [selected, skillId, bodies]);

  if (sourceType === "github") {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
        <Puzzle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 text-sm">
          <p className="font-medium">Sourced from a repository</p>
          <p className="text-xs text-muted-foreground">
            The skill files are fetched from{" "}
            {sourceUrl ? (
              <a href={sourceUrl} target="_blank" rel="noreferrer" className="break-all underline">
                {sourceUrl}
              </a>
            ) : (
              "its source repository"
            )}{" "}
            on install.
          </p>
        </div>
      </div>
    );
  }

  if (files === null) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading skill…
      </div>
    );
  }
  if (files.length === 0) {
    return error ? <p className="text-sm text-muted-foreground">{error}</p> : null;
  }

  const single = files.length === 1 && files[0].path.toLowerCase() === "skill.md";
  const body = selected ? bodies[selected] : undefined;

  const pane = (
    <div className="max-h-[480px] min-w-0 overflow-auto rounded-lg border border-border/60 bg-muted/20 p-4">
      {!body ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      ) : body.kind === "md" ? (
        <Streamdown className="prose prose-sm max-w-none dark:prose-invert">
          {body.value}
        </Streamdown>
      ) : body.kind === "text" ? (
        <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{body.value}</pre>
      ) : body.value ? (
        <a
          href={body.value}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-sm underline"
        >
          <ExternalLink className="h-4 w-4" />
          Open file
        </a>
      ) : (
        <p className="text-sm text-muted-foreground">Preview unavailable.</p>
      )}
    </div>
  );

  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Puzzle className="h-3.5 w-3.5" />
        {single ? "Skill instructions" : "Skill files"}
        {!single && <span className="tabular-nums">({files.length})</span>}
      </div>
      {single ? (
        pane
      ) : (
        <div className="grid gap-3 md:grid-cols-[12rem_minmax(0,1fr)]">
          <ul className="space-y-0.5 self-start rounded-lg border border-border/60 p-1.5">
            {files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  onClick={() => setSelected(f.path)}
                  className={cn(
                    "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-xs transition-colors",
                    selected === f.path
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:bg-muted/50"
                  )}
                >
                  <FileText className="h-3.5 w-3.5 shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{f.path}</span>
                  <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                    {fmtSize(f.size)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {pane}
        </div>
      )}
    </div>
  );
}

// Provenance facts for a catalog skill — source, repo, license, distribution.
// These come in as machine "key:value" tags; rendered here as a clean key/value
// list instead of loud chips. Hidden entirely when nothing useful is present.
function SkillFacts({ entry }: { entry: CatalogEntry }) {
  const tagVal = (prefix: string) =>
    entry.tags.find((t) => t.startsWith(prefix))?.slice(prefix.length) || null;
  const license = tagVal("license:");
  const facts: [string, string | null][] = [
    ["Source", entry.meta[0] ?? null],
    ["Repository", tagVal("repo:")],
    ["License", license === "NOASSERTION" ? "Not specified" : license],
    ["Distribution", tagVal("distribution:")],
  ];
  const shown = facts.filter(([, v]) => v);
  if (shown.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <dl className="divide-y divide-border/60">
        {shown.map(([k, v]) => (
          <div key={k} className="flex gap-4 px-4 py-2.5 text-sm">
            <dt className="w-28 shrink-0 text-muted-foreground">{k}</dt>
            <dd className="min-w-0 truncate font-medium">{v}</dd>
          </div>
        ))}
      </dl>
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

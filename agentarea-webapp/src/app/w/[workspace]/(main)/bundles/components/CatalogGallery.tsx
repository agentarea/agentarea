"use client";

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  useTransition,
} from "react";
import { useTranslations } from "next-intl";
import {
  ArrowDownAZ,
  BadgeCheck,
  Blocks,
  Bot,
  ChevronLeft,
  Compass,
  ExternalLink,
  FileText,
  Globe,
  Plug,
  Puzzle,
  Search,
  Sparkles,
  Star,
  Telescope,
} from "lucide-react";
import { parseAsString, parseAsStringLiteral, useQueryState } from "nuqs";
import { Streamdown } from "streamdown";
import DisplayMenu from "@/components/DisplayMenu";
import EmptyState from "@/components/EmptyState";
import EntityMark from "@/components/EntityMark";
import FormError from "@/components/FormError";
import HeaderTabs from "@/components/HeaderTabs";
import Table, { type Column } from "@/components/Table/Table";
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
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { HoverLink } from "@/components/ui/hover-link";
import { Input } from "@/components/ui/input";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
import ModelBadge from "@/components/ui/model-badge";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import {
  apiErrorMessage,
  formatApiError,
  isApiNotFound,
} from "@/lib/api-errors";
import { getCategoryIcon } from "@/lib/category-icons";
import type { StatusKind } from "@/lib/status";
import { cn } from "@/lib/utils";
import { getCookie, setCookie } from "@/utils/cookies";
import {
  addCatalogSkillToAgentAction,
  fetchCatalogItemAction,
  fetchCatalogPageAction,
  getSkillFileUrlAction,
  getSkillMarkdownAction,
  installCatalogAgentAction,
  installCatalogSkillAction,
  listActiveModelInstancesAction,
  listSkillFilesAction,
  listWorkspaceAgentsAction,
  type AgentLite,
  type WorkspaceModel,
} from "./actions";
import { BundlePlan } from "./BundlePlan";
import {
  ALL,
  DEFAULT_SORT,
  EXPLORE_VIEW_COOKIE,
  FEATURED_TAG,
  arr,
  isCatalogHosting,
  isCatalogProtocol,
  modelNameMatchesPreferred,
  normalize,
  HOSTING_LABELS,
  PROTOCOL_LABELS,
  SORT_KEYS,
  str,
  strArr,
  TYPE_KEYS,
  type CatalogEntry,
  type CatalogHosting,
  type CatalogProtocol,
  type CatalogType,
  type RawSpec,
  type RegistryItem,
  type SortMode,
} from "./catalog-data";
import {
  canFetchMore,
  catalogPagingReducer,
  hasMore as hasMoreItems,
  initialPaging,
  type CategoryFacet,
} from "./catalog-paging";
import type { CatalogSection } from "./catalog-sections";

// ── Registry types ──────────────────────────────────────────────────────────
// One gallery for every catalog type. The look-and-feel is shared; the type is
// just a tab. Each raw registry_item is normalized to a single CatalogEntry
// (see catalog-data.ts, shared with the SSR page) so every card renders through
// the same component regardless of type.

type LucideIcon = React.ComponentType<{ className?: string }>;

// Labels live in the CatalogPage messages (`types.<key>`).
const TYPES: { key: CatalogType; icon: LucideIcon }[] = [
  { key: "bundles", icon: Blocks },
  { key: "agents", icon: Bot },
  { key: "skills", icon: Puzzle },
  { key: "connections", icon: Plug },
];

/**
 * The way out of the catalog when it does not have the thing.
 *
 * Shown only in the empty state: the catalog runs to thousands of entries and
 * most searches land, so a standing banner above the list would tax everyone
 * who is about to succeed in order to serve the few who do not.
 *
 * Every route here is a real page, and "ask an agent" is not a figure of
 * speech either — `apps/api/agentarea_api/tools/mcp_servers_toolset.py`
 * exposes `create_spec` to agents through `get_platform_tools()`.
 */
// Texts live in the CatalogPage messages (`bringYourOwn.<type>.<key>`).
const BRING_YOUR_OWN: Record<CatalogType, { key: string; href?: string }[]> = {
  connections: [
    { key: "mcp", href: "/connections/add" },
    { key: "openapi", href: "/connections/add-openapi" },
    { key: "agent", href: "/workplace" },
  ],
  skills: [{ key: "write", href: "/skills/create" }],
  agents: [{ key: "build", href: "/agents/create" }],
  bundles: [{ key: "import", href: "/bundles/import" }],
};

const BRING_YOUR_OWN_ACTION_HREF: Record<CatalogType, string> = {
  connections: "/connections/add",
  skills: "/skills/create",
  agents: "/agents/create",
  bundles: "/bundles/import",
};

const VIEW_KEYS = ["grid", "table"] as const;

export type ViewMode = (typeof VIEW_KEYS)[number];

// ── Data (client-side, for infinite-scroll "load more" only) ──
// The first page of every filter combination is server-rendered (see
// explore/page.tsx); this only runs for appends, so it can never race the
// initial paint.

type BrowseParams = {
  type: CatalogType;
  offset: number;
  q: string;
  category: string;
  /** The nuqs value, so ALL or anything a hand-edited URL carries. */
  protocol: string;
  hosting: string;
  sort: SortMode;
};

async function fetchPage(params: BrowseParams) {
  return fetchCatalogPageAction({
    type: params.type,
    offset: params.offset,
    q: params.q || undefined,
    category: params.category === ALL ? undefined : params.category,
    // ALL, or junk from a hand-edited URL, means "don't filter" rather than a
    // request the server would reject.
    protocol: isCatalogProtocol(params.protocol) ? params.protocol : undefined,
    hosting: isCatalogHosting(params.hosting) ? params.hosting : undefined,
    sort: params.sort,
  });
}

// ── Shared "type switch in flight" signal ──
// The type tabs live in the ContentBlock subheader while the gallery lives in
// the content area, so the transition that wraps the SSR round-trip is owned
// here and consumed by both: the tabs trigger it, the gallery skeletons its
// content on `isPending` for the whole round-trip. This keeps the persistent
// chrome mounted and — crucially — avoids any flash of the previous type's data
// mid-switch (React holds the old tree during a transition, so a type-vs-seed
// comparison would briefly read stale; `isPending` doesn't).
//
// The kind of switch matters for how the wait is shown. Changing type makes the
// current results wrong, so they're replaced by a skeleton. Changing a filter
// within a type only narrows them, and search round-trips on every debounced
// keystroke — skeletoning there would strobe the whole list while you type — so
// the previous results stay on screen, dimmed, until the new page lands.
type PendingKind = "type" | "filters" | null;

type ExplorePending = {
  isPending: boolean;
  pendingKind: PendingKind;
  startTypeTransition: React.TransitionStartFunction;
  startFilterTransition: React.TransitionStartFunction;
};
const ExplorePendingContext = createContext<ExplorePending | null>(null);

export function ExplorePendingProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [isPending, startTransition] = useTransition();
  const [pendingKind, setPendingKind] = useState<PendingKind>(null);

  const startTypeTransition = useCallback<React.TransitionStartFunction>(
    (fn) => {
      setPendingKind("type");
      startTransition(fn);
    },
    [startTransition]
  );
  const startFilterTransition = useCallback<React.TransitionStartFunction>(
    (fn) => {
      setPendingKind("filters");
      startTransition(fn);
    },
    [startTransition]
  );

  const value = useMemo(
    () => ({
      isPending,
      pendingKind,
      startTypeTransition,
      startFilterTransition,
    }),
    [isPending, pendingKind, startTypeTransition, startFilterTransition]
  );
  return (
    <ExplorePendingContext.Provider value={value}>
      {children}
    </ExplorePendingContext.Provider>
  );
}

function useExplorePending() {
  return useContext(ExplorePendingContext);
}

// ── Type switcher (lives in the ContentBlock subheader) ──
// Lifted out of the gallery into the standard bordered subheader band — same
// pattern as the agents / connections pages — so it no longer sits inside the
// scrollable, padded content area. Shares the `type` URL state with the gallery
// below (same nuqs key), so selecting a tab drives both in lock-step.
export function ExploreTypeTabs({ initialType }: { initialType: CatalogType }) {
  // shallow:false re-runs the explore Server Component. The transition is owned
  // by ExplorePendingProvider (shared with the gallery) so its `isPending`
  // drives the gallery's content skeleton for the whole round-trip.
  const pending = useExplorePending();
  const [type, setType] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault(initialType).withOptions({
      shallow: false,
      startTransition: pending?.startTypeTransition,
    })
  );
  const [, setCategory] = useQueryState(
    "category",
    parseAsString.withDefault(ALL)
  );
  const [, setItemId] = useQueryState("item", parseAsString);
  const t = useTranslations("CatalogPage.types");

  return (
    <CountSegmentedControl
      items={TYPES.map(({ key, icon: Icon }) => ({
        value: key,
        label: (
          <span className="flex items-center gap-1.5 whitespace-nowrap">
            <Icon className="h-4 w-4" />
            {t(key)}
          </span>
        ),
      }))}
      value={type}
      onChange={(next) => {
        void setType(next);
        void setCategory(ALL);
        void setItemId(null);
      }}
      variant="solid"
      layoutId="catalog-type-control"
    />
  );
}

// Grid/table switcher for the subheader (right side, paired with the type
// tabs). Reuses the shared HeaderTabs control — same look as agents/connections.
// Hidden while a detail item is open (?item=), where there's nothing to switch.
export function ExploreViewToggle({
  initialView = "grid",
}: {
  initialView?: ViewMode;
}) {
  const [view, setView] = useQueryState(
    "view",
    parseAsStringLiteral(VIEW_KEYS).withDefault(initialView)
  );
  const [itemId] = useQueryState("item", parseAsString);
  const t = useTranslations("Common");

  // Restore the persisted view when landing on /explore without an explicit
  // ?view param (e.g. via the sidebar link). The server seeds `initialView`
  // from the same cookie to avoid a flash, but client-side restoration is the
  // authoritative path: a cached RSC or auth-gated SSR can serve a stale
  // default, so on mount we reconcile against the freshly-read cookie and write
  // the param if the saved choice differs from what's shown.
  useEffect(() => {
    const hasParam = new URLSearchParams(window.location.search).has("view");
    if (hasParam) return;
    const saved = getCookie(EXPLORE_VIEW_COOKIE);
    if ((saved === "table" || saved === "grid") && saved !== view) {
      void setView(saved);
    }
    // Run once on mount — restoring the persisted choice for this visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (itemId) return null;

  return (
    <HeaderTabs
      tabs={[
        { value: "table", label: t("table") },
        { value: "grid", label: t("grid") },
      ]}
      value={view}
      onChange={(v) => {
        // Persist so the choice survives leaving and returning to /explore.
        setCookie(EXPLORE_VIEW_COOKIE, v);
        void setView(v as ViewMode);
      }}
    />
  );
}

// ── Sort control (lives in the ContentBlock subheader) ──
// Ordering is applied server-side over the whole catalog, so this drives the
// same nuqs key the gallery reads and round-trips the Server Component
// (shallow:false) rather than reordering the loaded prefix.
export function ExploreSortSelect({
  initialSort = DEFAULT_SORT,
}: {
  initialSort?: SortMode;
}) {
  const pending = useExplorePending();
  const [sort, setSort] = useQueryState(
    "sort",
    parseAsStringLiteral(SORT_KEYS).withDefault(initialSort).withOptions({
      shallow: false,
      startTransition: pending?.startFilterTransition,
    })
  );
  const [itemId] = useQueryState("item", parseAsString);
  const t = useTranslations("CatalogPage.display");

  if (itemId) return null;

  return (
    <DisplayMenu>
      <MenuSectionLabel>{t("ordering")}</MenuSectionLabel>
      <MenuRow
        icon={<Sparkles className="h-3.5 w-3.5" />}
        label={t("recommended")}
        selected={sort === "recommended"}
        onClick={() => void setSort("recommended")}
      />
      <MenuRow
        icon={<ArrowDownAZ className="h-3.5 w-3.5" />}
        label={t("name")}
        selected={sort === "name"}
        onClick={() => void setSort("name")}
      />
    </DisplayMenu>
  );
}

// ── Component ──

type CatalogGalleryProps = {
  initialType: CatalogType;
  initialEntries: CatalogEntry[];
  /** Items matching the active filters across the whole catalog. */
  initialTotal: number;
  initialCategories: CategoryFacet[];
  /** MCP/API split; empty for every type but connections. */
  initialProtocols: CategoryFacet[];
  /** Vendor-hosted vs run on AgentArea; empty for every type but connections. */
  initialHostings?: CategoryFacet[];
  initialError?: string | null;
  /** Persisted grid/table choice (cookie), seeds the view nuqs default. */
  initialView?: ViewMode;
  /** Recommended / Popular shelves for the unfiltered catalog (catalog-sections.ts). */
  initialSections?: CatalogSection[];
};

export default function CatalogGallery({
  initialType,
  initialEntries,
  initialTotal,
  initialCategories,
  initialProtocols,
  initialHostings = [],
  initialError = null,
  initialView = "grid",
  initialSections = [],
}: CatalogGalleryProps) {
  // Catalog UI state lives in the URL (nuqs) so views are shareable/back-able.
  //
  // Every browse dimension — type, search, category, sort — uses shallow:false,
  // so changing any of them re-runs the explore Server Component and re-fetches
  // page 1 with those filters applied in SQL. Nothing is filtered or reordered
  // here: doing that over the loaded prefix hid matches that were never fetched
  // and spliced later pages into the middle of the rendered list.
  //
  // These keys are read-only here — the switchers live in the subheader
  // (ExploreTypeTabs / ExploreSortSelect / ExploreViewToggle) and drive the same
  // nuqs keys. The component is NOT remounted; the effect below re-seeds state
  // from the new SSR props, and `busy` skeletons the content while a switch is
  // in flight, so the persistent chrome never flashes.
  const [type] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault(initialType).withOptions({
      shallow: false,
    })
  );
  const [sort] = useQueryState(
    "sort",
    parseAsStringLiteral(SORT_KEYS).withDefault(DEFAULT_SORT).withOptions({
      shallow: false,
    })
  );
  const explorePending = useExplorePending();
  const [query, setQuery] = useQueryState(
    "q",
    parseAsString.withDefault("").withOptions({
      shallow: false,
      startTransition: explorePending?.startFilterTransition,
    })
  );
  const [category, setCategory] = useQueryState(
    "category",
    parseAsString.withDefault(ALL).withOptions({
      shallow: false,
      startTransition: explorePending?.startFilterTransition,
    })
  );
  const [protocol, setProtocol] = useQueryState(
    "protocol",
    parseAsString.withDefault(ALL).withOptions({
      shallow: false,
      startTransition: explorePending?.startFilterTransition,
    })
  );
  const [hosting, setHosting] = useQueryState(
    "hosting",
    parseAsString.withDefault(ALL).withOptions({
      shallow: false,
      startTransition: explorePending?.startFilterTransition,
    })
  );
  const [view] = useQueryState(
    "view",
    parseAsStringLiteral(VIEW_KEYS).withDefault(initialView)
  );
  // Pushed, not replaced: the browser's Back from a detail returns to the list.
  const [itemId, setItemId] = useQueryState(
    "item",
    parseAsString.withOptions({ history: "push" })
  );

  // Paging bookkeeping, seeded from the server-rendered first page (no initial
  // client fetch / flash). Kept in a reducer so the append/retry/exhaustion
  // rules are testable apart from the component — see catalog-paging.ts.
  const [paging, dispatch] = useReducer(
    catalogPagingReducer,
    undefined,
    () => ({
      ...initialPaging(),
      entries: initialEntries,
      total: initialTotal,
      categories: initialCategories,
      protocols: initialProtocols,
      hostings: initialHostings,
      error: initialError,
    })
  );

  // Typing shouldn't round-trip the server on every keystroke, so the input is
  // local and the URL follows it on a short debounce.
  const [draftQuery, setDraftQuery] = useState(query);
  useEffect(() => setDraftQuery(query), [query]);
  useEffect(() => {
    if (draftQuery === query) return;
    const t = setTimeout(() => void setQuery(draftQuery || null), 300);
    return () => clearTimeout(t);
  }, [draftQuery, query, setQuery]);

  // Deep-link fallback for ?item= that points outside the loaded page(s).
  const [deepItem, setDeepItem] = useState<CatalogEntry | null>(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const [deepError, setDeepError] = useState<string | null>(null);
  const [deepNotFound, setDeepNotFound] = useState(false);
  const [deepAttempt, setDeepAttempt] = useState(0);
  const tBundle = useTranslations("BundleInstall");
  const tCommon = useTranslations("Common");
  const tCatalog = useTranslations("CatalogPage");
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Re-seed whenever a server round-trip lands with a different page. The props
  // object identity changes on every SSR render, so a ref comparison is what
  // tells "the server handed us something new" from a local re-render.
  const seededFrom = useRef(initialEntries);
  useEffect(() => {
    if (seededFrom.current === initialEntries) return;
    seededFrom.current = initialEntries;
    dispatch({
      type: "seed",
      entries: initialEntries,
      total: initialTotal,
      categories: initialCategories,
      protocols: initialProtocols,
      hostings: initialHostings,
      error: initialError,
    });
  }, [
    initialEntries,
    initialTotal,
    initialCategories,
    initialProtocols,
    initialHostings,
    initialError,
  ]);

  const loadMore = useCallback(async () => {
    dispatch({ type: "appendStart" });
    try {
      const page = await fetchPage({
        type,
        // Entries are appended in server order, never reordered or
        // filtered here, so the loaded count IS the next offset.
        offset: paging.entries.length,
        q: query,
        category,
        protocol,
        hosting,
        sort,
      });
      if (page.error || !page.data) {
        dispatch({
          type: "fail",
          error: apiErrorMessage(page, tBundle("catalogLoadFailed")),
        });
        return;
      }
      dispatch({
        type: "append",
        entries: page.data.items.map((it) =>
          normalize(type, it as RegistryItem)
        ),
        total: page.data.total,
        categories: page.data.categories,
        protocols: page.data.protocols,
        hostings: page.data.hostings,
      });
    } catch (e) {
      console.error("Failed to load catalog page", e);
      dispatch({
        type: "fail",
        error: `${tBundle("catalogLoadFailed")}: ${formatApiError(e)}`,
      });
    }
  }, [type, query, category, protocol, hosting, sort, paging.entries, tBundle]);

  // Infinite scroll: auto-load the next page when the sentinel nears the
  // viewport. `canFetchMore` is the in-flight guard — a short page leaves the
  // sentinel inside the viewport, so without it this fires page after page.
  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !canFetchMore(paging)) return;
    const io = new IntersectionObserver(
      (obs) => {
        if (obs[0]?.isIntersecting) void loadMore();
      },
      { rootMargin: "600px" }
    );
    io.observe(node);
    return () => io.disconnect();
  }, [paging, loadMore]);

  // Deep-link fallback: if ?item= points at an entry that isn't in the loaded
  // page(s) (e.g. a shared link to something deep in the catalog), fetch that
  // one item by id so the detail still opens instead of silently falling back
  // to the grid.
  useEffect(() => {
    if (!itemId) {
      setDeepItem(null);
      setDeepError(null);
      setDeepNotFound(false);
      setDeepLoading(false);
      return;
    }
    if (paging.entries.some((e) => e.id === itemId)) return; // already in the list
    if (initialSections.some((sec) => sec.entries.some((e) => e.id === itemId)))
      return; // on a shelf
    if (deepItem?.id === itemId) return; // already fetched
    let alive = true;
    setDeepLoading(true);
    setDeepError(null);
    setDeepNotFound(false);
    fetchCatalogItemAction(itemId)
      .then((result) => {
        if (!alive) return;
        if (result.error || !result.data) {
          if (isApiNotFound(result)) setDeepNotFound(true);
          else setDeepError(apiErrorMessage(result, tBundle("itemLoadFailed")));
        } else {
          setDeepItem(normalize(type, result.data));
        }
        setDeepLoading(false);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        console.error("Failed to load catalog item", e);
        setDeepError(`${tBundle("itemLoadFailed")}: ${formatApiError(e)}`);
        setDeepLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [
    itemId,
    paging.entries,
    initialSections,
    type,
    deepItem?.id,
    deepAttempt,
    tBundle,
  ]);

  // Selected item (from ?item=) — resolved against the loaded page first, then
  // the deep-link fallback. When set, the main column shows the detail in place
  // — tabs + facets stay, so it feels like browsing a marketplace rather than a
  // full-page takeover.
  const active =
    (itemId
      ? (paging.entries.find((e) => e.id === itemId) ??
        initialSections
          .flatMap((sec) => sec.entries)
          .find((e) => e.id === itemId) ??
        null)
      : null) ?? (deepItem?.id === itemId ? deepItem : null);
  // Drives the empty-state copy + "Clear filters" affordance.
  const hasFilters =
    query.trim() !== "" ||
    category !== ALL ||
    protocol !== ALL ||
    hosting !== ALL;

  // A type switch invalidates the current results, so they're skeletoned. A
  // filter change only narrows them: the list stays and dims, which is what
  // keeps debounced search from strobing the page on every keystroke. Appends
  // are neither — they add to the list rather than replacing it.
  const pending = explorePending?.isPending ?? false;
  const busy = pending && explorePending?.pendingKind === "type";
  const refreshing = pending && !busy;
  const categories = useMemo(
    () => paging.categories.map((c) => [c.value, c.count] as [string, number]),
    [paging.categories]
  );
  const protocols = useMemo(
    () => paging.protocols.map((p) => [p.value, p.count] as [string, number]),
    [paging.protocols]
  );
  const hostings = useMemo(
    () =>
      (paging.hostings ?? []).map((h) => [h.value, h.count] as [string, number]),
    [paging.hostings]
  );

  // A detail replaces the list, so the list's scroll position is kept here and
  // put back on return: "Back to catalog" lands where the user left, with the
  // same filters (they never left the URL).
  const rootRef = useRef<HTMLDivElement | null>(null);
  const listScroll = useRef<number | null>(null);
  const openItem = useCallback(
    (id: string) => {
      const scroller = scrollContainerOf(rootRef.current);
      listScroll.current = scroller.scrollTop;
      void setItemId(id);
      scroller.scrollTop = 0;
    },
    [setItemId]
  );
  const closeItem = useCallback(() => void setItemId(null), [setItemId]);
  useEffect(() => {
    if (itemId || listScroll.current == null) return;
    const top = listScroll.current;
    listScroll.current = null;
    requestAnimationFrame(() => {
      scrollContainerOf(rootRef.current).scrollTop = top;
    });
  }, [itemId]);
  const moreAvailable = hasMoreItems(paging);

  return (
    <div ref={rootRef} className="flex gap-6">
      {/* Facet sidebar — always reserved on desktop so every catalog type keeps
          the same content width. Types without category facets still render the
          Category group with its All option. Counts come from the server and cover
          the whole catalog, so they do not drift as more pages load. A detail is
          full width: the facets belong to the list it came from. */}
      <aside className={cn("hidden w-52 shrink-0", !itemId && "lg:block")}>
        {busy ? (
          <FacetSkeleton />
        ) : (
          <>
            {/* Connections are not all MCP — an entry may be a plain HTTP API —
                so the split leads the sidebar when there is one to make. */}
            {protocols.length > 1 && (
              <FacetGroup
                label="Protocol"
                options={protocols}
                labels={PROTOCOL_LABELS}
                selected={protocol}
                onSelect={(v) => {
                  void setProtocol(v === ALL ? null : v);
                  void setItemId(null);
                }}
              />
            )}
            {/* Where an MCP connection runs: connecting means an OAuth sign-in
                for one and keys for a process we start for the other. */}
            {hostings.length > 1 && (
              <FacetGroup
                label="Runs"
                options={hostings}
                labels={HOSTING_LABELS}
                selected={hosting}
                onSelect={(v) => {
                  void setHosting(v === ALL ? null : v);
                  void setItemId(null);
                }}
              />
            )}
            <FacetGroup
              label="Category"
              options={categories}
              icons={getCategoryIcon}
              selected={category}
              onSelect={(v) => {
                void setCategory(v === ALL ? null : v);
                void setItemId(null);
              }}
            />
          </>
        )}
      </aside>

      {/* Main */}
      <div className="min-w-0 flex-1 space-y-4">
        {active ? (
          <DetailView entry={active} onBack={closeItem} />
        ) : itemId ? (
          <DeepItemStatus onBack={closeItem}>
            {deepLoading ? (
              <StatusIndicator kind="running" size="sm">
                Loading…
              </StatusIndicator>
            ) : deepError && !deepNotFound ? (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
                <FormError className="flex-1">{deepError}</FormError>
                <Button
                  size="xs"
                  variant="outline"
                  className="self-start"
                  onClick={() => {
                    setDeepError(null);
                    setDeepAttempt((n) => n + 1);
                  }}
                >
                  {tCommon("retry")}
                </Button>
              </div>
            ) : (
              <EmptyState
                title={tCatalog("empty.notFoundTitle")}
                description={tCatalog("empty.notFoundDescription")}
                iconsType="404"
                action={{
                  label: tCatalog("empty.backToCatalog"),
                  onClick: () => void setItemId(null),
                }}
              />
            )}
          </DeepItemStatus>
        ) : (
          <>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={draftQuery}
                onChange={(e) => setDraftQuery(e.target.value)}
                placeholder={tCatalog(`search.${type}`)}
                aria-label={tCatalog(`search.${type}`)}
                className="pl-9"
              />
            </div>

            {paging.error && (
              <div className="flex items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/30">
                <StatusIndicator kind="failed" size="sm" className="text-sm">
                  {paging.error}
                </StatusIndicator>
                {/* A failed page used to end infinite scroll for good. It's a
                  retry, not the end of the catalog. */}
                {moreAvailable && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void loadMore()}
                  >
                    {tCommon("retry")}
                  </Button>
                )}
              </div>
            )}
            {busy && <ContentSkeleton view={view} />}
            {!busy &&
              !refreshing &&
              paging.entries.length === 0 &&
              !paging.error && (
                <EmptyState
                  title={tCatalog(
                    hasFilters ? "empty.noMatchesTitle" : "empty.nothingTitle"
                  )}
                  description={tCatalog(
                    hasFilters
                      ? "empty.noMatchesDescription"
                      : "empty.nothingDescription"
                  )}
                  icons={hasFilters ? [Telescope, Compass, Search] : undefined}
                  // Failing to find something is the one moment where the way
                  // out of the catalog is worth showing. "Clear filters" on its
                  // own assumed the answer was always in here and you had
                  // merely filtered wrong.
                  hints={BRING_YOUR_OWN[type].map(({ key, href }) => ({
                    text: tCatalog(`bringYourOwn.${type}.${key}`),
                    href,
                  }))}
                  action={
                    hasFilters
                      ? {
                          label: tCatalog("empty.clearFilters"),
                          onClick: () => {
                            setDraftQuery("");
                            void setQuery(null);
                            void setCategory(null);
                            void setProtocol(null);
                          },
                        }
                      : undefined
                  }
                  additionAction={{
                    label: tCatalog(`bringYourOwn.${type}.action`),
                    href: BRING_YOUR_OWN_ACTION_HREF[type],
                  }}
                />
              )}

            {/* Shelves are server-picked for the unfiltered catalog; any filter
                round-trips the page and the next render simply has none. */}
            {!busy &&
              !hasFilters &&
              sort === DEFAULT_SORT &&
              initialSections.map((sec) => (
                <section key={sec.key} className="space-y-2">
                  <CatalogShelfHeading
                    title={sec.title}
                    description={sec.description}
                  />
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                    {sec.entries.map((e) => (
                      <CatalogCard
                        key={e.id}
                        entry={e}
                        onOpen={() => openItem(e.id)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            {!busy &&
              !hasFilters &&
              sort === DEFAULT_SORT &&
              initialSections.length > 0 &&
              paging.entries.length > 0 && (
                <CatalogShelfHeading
                  title={tCatalog(`allOfType.${type}`)}
                  description={tCatalog("inCatalog", {
                    count: paging.total.toLocaleString(),
                  })}
                />
              )}

            {!busy && paging.entries.length > 0 && (
              <div
                className={cn(
                  "transition-opacity",
                  refreshing && "pointer-events-none opacity-50"
                )}
                aria-busy={refreshing}
              >
                {view === "grid" ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
                    {paging.entries.map((e) => (
                      <CatalogCard
                        key={e.id}
                        entry={e}
                        onOpen={() => openItem(e.id)}
                      />
                    ))}
                  </div>
                ) : (
                  <CatalogTable
                    entries={paging.entries}
                    onOpen={(e) => openItem(e.id)}
                  />
                )}
              </div>
            )}

            {/* Infinite-scroll sentinel + manual fallback. Mounted whenever the
              catalog has more, including when this page rendered nothing — a
              filter whose matches all sit further in used to render "No matches"
              here and strand the rest of the catalog. */}
            {!busy && !refreshing && moreAvailable && (
              <>
                <div ref={sentinelRef} className="h-px" aria-hidden />
                <div className="flex justify-center pt-2">
                  {paging.status === "appending" ? (
                    <StatusIndicator
                      kind="running"
                      size="sm"
                      aria-label="Loading…"
                      title="Loading…"
                    />
                  ) : (
                    !paging.error && (
                      <Button variant="outline" onClick={() => void loadMore()}>
                        Load more
                      </Button>
                    )
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function CatalogShelfHeading({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-baseline gap-2 pt-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="truncate text-xs text-muted-foreground">{description}</p>
    </div>
  );
}

// ── Table view (compact, scannable; same click → drawer) ──

// Fixed layout with the category in its own column: inline after the title it
// landed wherever the name ended, so no two rows lined up.
const CATALOG_COLUMNS: Column<CatalogEntry>[] = [
  {
    header: "Name",
    accessor: "title",
    headerClassName: "w-[40%] md:w-[32%]",
    render: (_, e) =>
      e ? (
        <div className="flex min-w-0 items-center gap-2.5">
          <EntityMark
            identity={e.identity}
            brandFallback={false}
            className="h-7 w-7 shrink-0 rounded-md border border-border/60 bg-white p-[3px] text-[10px] dark:bg-zinc-800"
          />
          <span className="min-w-0 truncate text-sm font-medium">
            {e.title}
          </span>
          {e.verified && (
            <BadgeCheck className="h-3.5 w-3.5 shrink-0 text-blue-500" />
          )}
        </div>
      ) : null,
  },
  {
    header: "Category",
    accessor: "category",
    headerClassName: "hidden w-[200px] sm:table-cell",
    cellClassName: "hidden sm:table-cell",
    render: (_, e) =>
      e?.category ? <CategoryBadge category={e.category} /> : null,
  },
  {
    header: "Description",
    accessor: "description",
    headerClassName: "hidden md:table-cell",
    cellClassName: "hidden md:table-cell",
    render: (_, e) => (
      <div className="table-description truncate">{e?.description}</div>
    ),
  },
];

function CatalogTable({
  entries,
  onOpen,
}: {
  entries: CatalogEntry[];
  onOpen: (e: CatalogEntry) => void;
}) {
  return (
    <Table
      className="table-fixed"
      data={entries}
      columns={CATALOG_COLUMNS}
      onRowClick={onOpen}
    />
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
  labels,
  icons,
  selected,
  onSelect,
}: {
  label: string;
  options: [string, number][];
  /** Display names for machine values ("mcp" reads as "Mcp" otherwise). */
  labels?: Record<string, string>;
  /** Icon per option value. Omitted by facets whose values are not topics. */
  icons?: (value: string) => LucideIcon;
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
        {rows.map(([value, count]) => {
          // "All" is the absence of a filter, not a topic, so it stays bare —
          // but it still takes the icon's width so the labels line up.
          const Icon = icons && value !== ALL ? icons(value) : null;
          return (
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
              {icons &&
                (Icon ? (
                  <Icon className="h-3.5 w-3.5 shrink-0" />
                ) : (
                  <span className="h-3.5 w-3.5 shrink-0" />
                ))}
              <span className="min-w-0 flex-1 truncate text-left capitalize">
                {value === ALL ? "All" : (labels?.[value] ?? value)}
              </span>
              {count !== null && (
                <span className="text-[10px] tabular-nums text-muted-foreground">
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ── Card (uniform across every type) ──

/**
 * A catalog entry's category, with the icon the sidebar files it under.
 *
 * The three sources spell categories differently ("Data & Analytics" vs
 * "data"), so the text alone does not read as the same bucket across types.
 * The icon does, and it matches the facet the entry is reachable through.
 */
function CategoryBadge({ category }: { category: string }) {
  // createElement rather than a capitalised local: the lookup returns an
  // existing icon, but assigning one to `const Icon` here reads to
  // react-hooks/static-components as defining a component mid-render.
  const icon = getCategoryIcon(category);
  return (
    <Badge
      variant="light"
      size="sm"
      className="shrink-0 gap-1 whitespace-nowrap capitalize"
    >
      {React.createElement(icon, { className: "h-3 w-3" })}
      {category}
    </Badge>
  );
}

/**
 * What a connection speaks. The catalog tile shows the vendor's own logo, so
 * without this an MCP server and an HTTP API to the same vendor are
 * indistinguishable — and "Connections" no longer implies MCP.
 */
function ProtocolBadge({ protocol }: { protocol: CatalogProtocol }) {
  return (
    <Badge variant="secondary" size="sm" className="gap-1 font-normal">
      {protocol === "mcp" ? (
        // mcp.svg is fill="currentColor"; as a mask it inherits the badge's
        // text colour instead of fighting the theme.
        <span
          aria-hidden
          className="h-3 w-3 bg-current [mask-image:url(/mcp.svg)] [mask-position:center] [mask-repeat:no-repeat] [mask-size:contain] [-webkit-mask-image:url(/mcp.svg)] [-webkit-mask-position:center] [-webkit-mask-repeat:no-repeat] [-webkit-mask-size:contain]"
        />
      ) : (
        <Globe className="h-3 w-3" />
      )}
      {PROTOCOL_LABELS[protocol]}
    </Badge>
  );
}

function CatalogCard({
  entry,
  onOpen,
}: {
  entry: CatalogEntry;
  onOpen: () => void;
}) {
  return (
    <button
      onClick={onOpen}
      className="group flex flex-col overflow-hidden rounded-lg border border-border/60 bg-white text-left transition-shadow hover:shadow-md dark:border-zinc-700/60 dark:bg-zinc-900"
    >
      <div className="relative flex h-20 items-center justify-center gap-1.5 border-b border-border/40 bg-[radial-gradient(circle,theme(colors.zinc.200)_1px,transparent_1px)] [background-size:12px_12px] dark:bg-[radial-gradient(circle,theme(colors.zinc.800)_1px,transparent_1px)]">
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
        {/* A bundle's value is the integrations it wires up, so when it has
            no artwork of its own they say more than a monogram would. */}
        {entry.identity.sources.length === 0 &&
        entry.integrations.length > 0 ? (
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
          <EntityMark
            identity={entry.identity}
            brandFallback={false}
            className="h-[52px] w-[52px] rounded-xl border border-border/60 bg-white p-1.5 text-xs shadow-sm dark:bg-zinc-800"
          />
        )}
        <span className="absolute right-2 top-2">
          <HoverLink text="View" />
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1 p-3">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold">{entry.title}</span>
          {entry.category && <CategoryBadge category={entry.category} />}
        </div>
        <p className="table-description line-clamp-2">{entry.description}</p>
        {(entry.protocol || entry.meta.length > 0) && (
          <div className="mt-auto flex flex-wrap items-center gap-1 pt-1.5">
            {entry.protocol && <ProtocolBadge protocol={entry.protocol} />}
            {entry.meta.map((m) => (
              <Badge
                key={m}
                variant="secondary"
                size="sm"
                className="font-normal"
              >
                {m}
              </Badge>
            ))}
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

function DetailView({
  entry,
  onBack,
}: {
  entry: CatalogEntry;
  onBack: () => void;
}) {
  const [state, setState] = useState<InstallState>({ phase: "idle" });
  const tBundle = useTranslations("BundleInstall");
  // Bundles open an inline configure-then-install step rather than installing on
  // the first click (pick model, skip connections, tune policies, then commit).
  const [configuring, setConfiguring] = useState(false);

  const spec = entry.spec;
  const rawMeta = (spec.raw_spec as RawSpec | undefined)?.metadata as
    | RawSpec
    | undefined;
  const tier = (str(rawMeta?.["agentarea:setup_tier"]) ??
    "unverified") as SetupTier;
  const isCatalogApi = entry.protocol === "api";
  const hosting = connectionHosting(entry);

  // Machine tags ("category:x", "repo:y", "featured"…) are provenance, not
  // topical labels — keep them out of the chip row (surfaced elsewhere instead).
  // Bundle capabilities get their own labeled row, so drop them here too.
  const capabilitySet = new Set(bundleCapabilities(spec));
  const topicalTags = entry.tags.filter(
    (t) => !t.includes(":") && t !== FEATURED_TAG && !capabilitySet.has(t)
  );

  // Setup runs on a connections page — the catalog never configures inline.
  // An MCP entry links to its spec, which the API resolves by catalog item id
  // (ADR-003); an HTTP API entry to its connect form.
  const connectHref = isCatalogApi
    ? `/connections/catalog/${entry.id}`
    : `/connections/create/${entry.id}`;

  useEffect(() => {
    // Reset only when the selected item changes.
    setState({ phase: "idle" });
    setConfiguring(false);
  }, [entry.id]);

  async function installAgent() {
    setState({ phase: "loading" });
    try {
      // entry.id is the registry_item id; the endpoint forks a tenant copy
      // (copy-on-write) and is idempotent if already installed.
      const result = await installCatalogAgentAction(entry.id);
      if (result.error || !result.data) {
        setState({
          phase: "error",
          message: apiErrorMessage(result, tBundle("agentInstallFailed")),
        });
        return;
      }
      setState({ phase: "done", created: 1 });
    } catch (e) {
      console.error("Failed to install catalog agent", e);
      setState({
        phase: "error",
        message: `${tBundle("agentInstallFailed")}: ${formatApiError(e)}`,
      });
    }
  }

  const installing = state.phase === "loading";

  const isBundle = entry.type === "bundles";

  return (
    <div className={cn("space-y-8", isBundle ? "max-w-[1120px]" : "max-w-2xl")}>
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
          <EntityMark
            identity={entry.identity}
            brandFallback={false}
            className="h-12 w-12 shrink-0 rounded-lg border border-border/60 bg-white p-1.5 text-sm shadow-sm dark:bg-zinc-800"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold tracking-tight">
                {entry.title}
              </h2>
              {entry.verified && (
                <Badge variant="blue" size="sm" className="gap-1">
                  <BadgeCheck className="h-3 w-3" />
                  Verified
                </Badge>
              )}
              {entry.protocol && <ProtocolBadge protocol={entry.protocol} />}
              {entry.category && <CategoryBadge category={entry.category} />}
              {hosting && (
                <Badge variant="light" size="sm">
                  {hosting === "agentarea"
                    ? HOSTING_LABELS.agentarea
                    : `Hosted by ${hostOf(str(spec.url)) ?? "vendor"}`}
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
          ) : entry.type === "connections" ? (
            <StartAgentButton asChild size="xs">
              <Link href={connectHref}>Connect</Link>
            </StartAgentButton>
          ) : isBundle && configuring ? null : (
            <StartAgentButton
              size="xs"
              onClick={() => (isBundle ? setConfiguring(true) : installAgent())}
              isLoading={installing}
            >
              {isBundle ? "Use this bundle" : "Add to workspace"}
            </StartAgentButton>
          )}
        </CatalogActionSlot>
      </div>

      {/* install feedback */}
      {state.phase === "error" && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/30">
          <StatusIndicator
            kind="failed"
            size="sm"
            iconClassName="mt-0.5 h-4 w-4"
            className="text-sm"
          >
            {state.message}
          </StatusIndicator>
        </div>
      )}
      {state.phase === "done" && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-900/50 dark:bg-emerald-950/30">
          <StatusIndicator
            kind="done"
            size="sm"
            iconClassName="h-4 w-4"
            className="text-sm"
          >
            {entry.type === "agents"
              ? "Added to your workspace — it's now an editable copy you own."
              : `Installed — ${state.created} entities created.`}
          </StatusIndicator>
        </div>
      )}

      {(capabilitySet.size > 0 || topicalTags.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {[...capabilitySet].map((c) => (
            <Badge
              key={c}
              variant="light"
              size="sm"
              className="gap-1 capitalize"
            >
              <Sparkles className="h-3 w-3" />
              {c.replace(/[-_]+/g, " ")}
            </Badge>
          ))}
          {topicalTags.slice(0, 12).map((t) => (
            <Badge key={t} variant="light" size="sm">
              {t}
            </Badge>
          ))}
        </div>
      )}

      {/* details */}
      <div className="space-y-5 border-t border-border/60 pt-6">
        {isBundle && (
          <BundlePlan
            source={JSON.stringify(spec)}
            configuring={configuring}
            onCancel={() => setConfiguring(false)}
          />
        )}
        {entry.type === "agents" && <PreferredModels models={entry.meta} />}
        {entry.type === "connections" && !isCatalogApi && (
          <>
            <ConnectionSetup tier={tier} />
            <ConnectionHow entry={entry} />
            <ConnectionNeeds entry={entry} />
          </>
        )}
        {entry.type === "connections" && <ConnectionFacts entry={entry} />}
        {entry.type === "skills" && (
          <>
            <SkillContent
              skillId={entry.id}
              sourceType={str(spec.source_type) ?? "content"}
              sourceUrl={str(spec.source_url)}
              content={str(spec.content)}
            />
            <SkillFacts entry={entry} />
          </>
        )}
      </div>
    </div>
  );
}

// A catalog agent declares model *preferences* (slugs); the backend never binds
// a model on install (that's a per-workspace instance). This surfaces those
// preferences and, by fetching the workspace's configured models, suggests which
// one to pick — highlighting an available match or saying plainly when none fit.
function PreferredModels({ models }: { models: string[] }) {
  const t = useTranslations("BundleInstall");
  const tCommon = useTranslations("Common");
  const [instances, setInstances] = useState<WorkspaceModel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    listActiveModelInstancesAction()
      .then((result) => {
        if (!active) return;
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("modelsLoadFailed")));
          return;
        }
        setInstances(result.data);
      })
      .catch((err: unknown) => {
        console.error("Failed to load workspace models", err);
        if (active) {
          setError(`${t("modelsLoadFailed")}: ${formatApiError(err)}`);
        }
      });
    return () => {
      active = false;
    };
  }, [t, attempt]);

  if (models.length === 0) return null;

  const matchFor = (slug: string) =>
    (instances ?? []).filter((mi) =>
      modelNameMatchesPreferred(str(mi.model_name) ?? "", slug)
    );
  const anyMatch =
    instances != null && models.some((s) => matchFor(s).length > 0);

  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Bot className="h-3.5 w-3.5" />
        Preferred models
        <span className="tabular-nums">({models.length})</span>
      </div>
      <ul className="space-y-1">
        {models.map((slug) => {
          const best = matchFor(slug)[0];
          return (
            <li
              key={slug}
              className="flex items-center justify-between gap-2 rounded bg-muted/50 px-2 py-1.5 text-sm"
            >
              <span className="truncate">{slug}</span>
              {instances == null ? null : best ? (
                <span className="flex shrink-0 items-center gap-1.5">
                  <ModelBadge
                    size="sm"
                    className="bg-transparent px-0 py-0"
                    providerName={best.provider_name ?? undefined}
                    iconUrl={best.provider_icon_url ?? undefined}
                    modelDisplayName={
                      best.model_display_name || best.model_name || slug
                    }
                  />
                  <StatusIndicator kind="active" size="sm">
                    In your workspace
                  </StatusIndicator>
                </span>
              ) : (
                <StatusIndicator kind="draft" size="sm">
                  Not configured
                </StatusIndicator>
              )}
            </li>
          );
        })}
      </ul>
      {error ? (
        <div className="mt-1.5 flex flex-col gap-2 sm:flex-row sm:items-start">
          <FormError className="flex-1">{error}</FormError>
          <Button
            size="xs"
            variant="outline"
            className="self-start"
            onClick={() => {
              setError(null);
              setAttempt((n) => n + 1);
            }}
          >
            {tCommon("retry")}
          </Button>
        </div>
      ) : (
        <p className="mt-1.5 text-[11px] text-muted-foreground">
          {instances == null
            ? "Checking your workspace models…"
            : anyMatch
              ? "The agent is added without a model — pick a suggested one (or any other) before running it."
              : "None are configured in your workspace yet — add a provider, then pick a model for this agent."}
        </p>
      )}
    </div>
  );
}

function ConnectionSetup({ tier }: { tier: SetupTier }) {
  const COPY: Record<
    SetupTier,
    { kind: StatusKind; title: string; detail: string }
  > = {
    one_click: {
      kind: "draft",
      title: "One-click connect",
      detail: "Authorize access in the next step — nothing to set up.",
    },
    oauth: {
      kind: "draft",
      title: "Ready to connect",
      detail: "Click Connect, then sign in and approve access.",
    },
    needs_oauth_app: {
      kind: "attention",
      title: "Needs an OAuth app",
      detail:
        "This vendor requires a one-time OAuth app (client ID/secret). You can add it now and finish auth on the connection page.",
    },
    needs_tenant_config: {
      kind: "attention",
      title: "Enter your workspace URL",
      detail:
        "This connection is hosted in your own tenant — paste your full MCP URL.",
    },
    unverified: {
      kind: "attention",
      title: "Not verified by AgentArea",
      detail:
        "We haven't tested this connection end to end. Connect tries the standard setup; some servers need extra configuration afterwards.",
    },
  };
  const c = COPY[tier];
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
        <StatusIndicator
          kind={c.kind}
          size="sm"
          className="text-sm font-medium"
        >
          {c.title}
        </StatusIndicator>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{c.detail}</p>
        </div>
      </div>
    </div>
  );
}

// Presentation capabilities a bundle advertises ("interactive", "write"…),
// carried in metadata — shown beside its tags, not mixed into them.
function bundleCapabilities(spec: RawSpec): string[] {
  return strArr((spec.metadata as RawSpec | undefined)?.capabilities);
}

// Primary action for a catalog skill: attach it to an agent. A workspace skill
// that isn't attached to any agent does nothing, so the high-intent path is
// "add to agent" — fork the catalog skill into the workspace (copy-on-write,
// idempotent) and merge it into the chosen agent's skill set. "Add to
// workspace" stays as a quiet secondary for the library case.
function AddSkillToAgent({ skillId }: { skillId: string }) {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<AgentLite[] | null>(null);
  const [phase, setPhase] = useState<"idle" | "loading" | "done" | "error">(
    "idle"
  );
  const [message, setMessage] = useState("");
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [agentsAttempt, setAgentsAttempt] = useState(0);
  const [result, setResult] = useState<{ label: string; href: string } | null>(
    null
  );
  const tBundle = useTranslations("BundleInstall");
  const tCommon = useTranslations("Common");

  // Lazy-load the workspace agents the first time the picker opens.
  useEffect(() => {
    if (!open || agents !== null) return;
    let active = true;
    setAgentsError(null);
    listWorkspaceAgentsAction()
      .then((res) => {
        if (!active) return;
        if (res.error || !res.data) {
          setAgentsError(apiErrorMessage(res, tBundle("agentsLoadFailed")));
          return;
        }
        setAgents(res.data);
      })
      .catch((e: unknown) => {
        console.error("Failed to load workspace agents", e);
        if (active) {
          setAgentsError(
            `${tBundle("agentsLoadFailed")}: ${formatApiError(e)}`
          );
        }
      });
    return () => {
      active = false;
    };
  }, [open, agents, agentsAttempt, tBundle]);

  async function addToWorkspace() {
    setPhase("loading");
    try {
      const installed = await installCatalogSkillAction(skillId);
      if (installed.error || !installed.data) {
        setMessage(apiErrorMessage(installed, tBundle("skillInstallFailed")));
        setPhase("error");
        return;
      }
      setResult({ label: "Go to Skills", href: "/skills" });
      setPhase("done");
    } catch (e) {
      console.error("Failed to install catalog skill", e);
      setMessage(`${tBundle("skillInstallFailed")}: ${formatApiError(e)}`);
      setPhase("error");
    }
  }

  async function addToAgent(agent: AgentLite) {
    setOpen(false);
    setPhase("loading");
    const label = tBundle("skillAttachFailed", { agent: agent.name });
    try {
      const attached = await addCatalogSkillToAgentAction(skillId, agent.id);
      if (attached.error || !attached.data) {
        setMessage(apiErrorMessage(attached, label));
        setPhase("error");
        return;
      }
      setResult({ label: `Open ${agent.name}`, href: `/agents/${agent.id}` });
      setPhase("done");
    } catch (e) {
      console.error("Failed to add catalog skill to agent", e);
      setMessage(`${label}: ${formatApiError(e)}`);
      setPhase("error");
    }
  }

  if (phase === "done" && result) {
    return (
      <div className="flex flex-col items-start gap-1.5 md:items-end">
        <StatusIndicator kind="done" size="sm" className="font-medium">
          Added
        </StatusIndicator>
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
              {agentsError ? (
                <div className="space-y-2 p-3">
                  <FormError>{agentsError}</FormError>
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => setAgentsAttempt((n) => n + 1)}
                  >
                    {tCommon("retry")}
                  </Button>
                </div>
              ) : agents === null ? (
                <StatusIndicator kind="running" size="sm">
                  Loading…
                </StatusIndicator>
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
                      <CommandItem
                        key={a.id}
                        value={a.name}
                        onSelect={() => addToAgent(a)}
                      >
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
        <StatusIndicator
          kind="failed"
          size="sm"
          className="max-w-[15rem] text-xs md:text-right"
        >
          {message}
        </StatusIndicator>
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
  | { kind: "link"; value: string }
  | { kind: "error"; value: string };

// Extensions we can safely preview inline as text. Anything else gets an
// "open" link to its presigned URL instead of a garbled inline dump.
const TEXT_EXT = new Set([
  "md",
  "markdown",
  "txt",
  "py",
  "js",
  "ts",
  "tsx",
  "jsx",
  "json",
  "yaml",
  "yml",
  "sh",
  "bash",
  "toml",
  "ini",
  "cfg",
  "csv",
  "html",
  "css",
  "xml",
  "sql",
  "env",
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
// A catalog skill is a read-only registry projection; its body comes from one of
// three sources, each rendered by its own single-purpose view:
//   github          → files are fetched on install, so link to the source
//   inlined content → the SKILL.md lives in the registry spec; render it
//   multi-file pkg  → browse the file tree via the skill-files API
function SkillContent({
  skillId,
  sourceType,
  sourceUrl,
  content,
}: {
  skillId: string;
  sourceType: string;
  sourceUrl: string | null;
  content: string | null;
}) {
  if (sourceType === "github") return <SkillSourceLink sourceUrl={sourceUrl} />;
  if (content) return <SkillMarkdown content={content} />;
  return <SkillPackageFiles skillId={skillId} />;
}

function SkillSourceLink({ sourceUrl }: { sourceUrl: string | null }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
      <Puzzle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 text-sm">
        <p className="font-medium">Sourced from a repository</p>
        <p className="text-xs text-muted-foreground">
          The skill files are fetched from{" "}
          {sourceUrl ? (
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              className="break-all underline"
            >
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

function SkillMarkdown({ content }: { content: string }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <Puzzle className="h-3.5 w-3.5" />
        Skill instructions
      </div>
      <div className="max-h-[480px] overflow-auto rounded-lg border border-border/60 bg-muted/20 p-4">
        <Streamdown className="prose prose-sm max-w-none dark:prose-invert">
          {skillBody(content)}
        </Streamdown>
      </div>
    </div>
  );
}

// Browse a materialized (installed / multi-file) skill package via the skill-files
// API. Catalog content skills never reach here — their SKILL.md is inlined and
// rendered by SkillMarkdown.
function SkillPackageFiles({ skillId }: { skillId: string }) {
  const t = useTranslations("BundleInstall");
  const tCommon = useTranslations("Common");
  const [files, setFiles] = useState<SkillFile[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [bodies, setBodies] = useState<Record<string, FileBody>>({});
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const requested = useRef<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    listSkillFilesAction(skillId)
      .then((result) => {
        if (!active) return;
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("skillFilesLoadFailed")));
          return;
        }
        const fs = result.data;
        setFiles(fs);
        const def =
          fs.find((f) => f.path.toLowerCase() === "skill.md") ?? fs[0] ?? null;
        setSelected(def?.path ?? null);
      })
      .catch((e: unknown) => {
        if (!active) return;
        console.error("Failed to load skill files:", e);
        setError(`${t("skillFilesLoadFailed")}: ${formatApiError(e)}`);
      });
    return () => {
      active = false;
    };
  }, [skillId, t, attempt]);

  const retryFile = (path: string) => {
    requested.current.delete(path);
    setBodies(({ [path]: _failed, ...rest }) => rest);
  };

  // Lazily load the selected file's body. SKILL.md comes from /content; other
  // files resolve to a presigned URL we then fetch (text) or link to.
  useEffect(() => {
    if (!selected || bodies[selected] || requested.current.has(selected))
      return;
    requested.current.add(selected);
    let active = true;
    void (async () => {
      try {
        const failed = (result: {
          error?: unknown;
          status?: number;
        }): FileBody => ({
          kind: "error",
          value: apiErrorMessage(result, t("skillFileLoadFailed")),
        });
        if (selected.toLowerCase() === "skill.md") {
          const md = await getSkillMarkdownAction(skillId);
          if (active)
            setBodies((b) => ({
              ...b,
              [selected]:
                md.error || md.data === undefined
                  ? failed(md)
                  : { kind: "md", value: skillBody(md.data) },
            }));
          return;
        }
        const fileUrl = await getSkillFileUrlAction(skillId, selected);
        if (fileUrl.error || !fileUrl.data) {
          if (active) setBodies((b) => ({ ...b, [selected]: failed(fileUrl) }));
          return;
        }
        const url = fileUrl.data;
        if (isTextFile(selected)) {
          try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const text = await res.text();
            if (active)
              setBodies((b) => ({
                ...b,
                [selected]: { kind: "text", value: text },
              }));
            return;
          } catch (err) {
            // Cross-origin / unreadable: offer the plain open link instead.
            console.warn("Skill file preview unavailable", err);
          }
        }
        if (active)
          setBodies((b) => ({
            ...b,
            [selected]: { kind: "link", value: url },
          }));
      } catch (err) {
        console.error("Failed to load skill file", err);
        if (active)
          setBodies((b) => ({
            ...b,
            [selected]: {
              kind: "error",
              value: `${t("skillFileLoadFailed")}: ${formatApiError(err)}`,
            },
          }));
      }
    })();
    return () => {
      active = false;
    };
  }, [selected, skillId, bodies, t]);

  if (error) {
    return (
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <FormError className="flex-1">{error}</FormError>
        <Button
          size="xs"
          variant="outline"
          className="self-start"
          onClick={() => {
            setError(null);
            setAttempt((n) => n + 1);
          }}
        >
          {tCommon("retry")}
        </Button>
      </div>
    );
  }
  if (files === null) {
    return (
      <StatusIndicator kind="running" size="sm">
        Loading skill…
      </StatusIndicator>
    );
  }
  if (files.length === 0) return null;

  const single =
    files.length === 1 && files[0].path.toLowerCase() === "skill.md";
  const body = selected ? bodies[selected] : undefined;

  const pane = (
    <div className="max-h-[480px] min-w-0 overflow-auto rounded-lg border border-border/60 bg-muted/20 p-4">
      {!body ? (
        <StatusIndicator kind="running" size="sm">
          Loading…
        </StatusIndicator>
      ) : body.kind === "md" ? (
        <Streamdown className="prose prose-sm max-w-none dark:prose-invert">
          {body.value}
        </Streamdown>
      ) : body.kind === "text" ? (
        <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
          {body.value}
        </pre>
      ) : body.kind === "error" ? (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <FormError className="flex-1">{body.value}</FormError>
          {selected && (
            <Button
              size="xs"
              variant="outline"
              className="self-start"
              onClick={() => retryFile(selected)}
            >
              {tCommon("retry")}
            </Button>
          )}
        </div>
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

// ── Connection details ──
// What the catalog already knows about a connection, said in words: who
// publishes it, where it runs, and what to have ready before clicking Connect.

type ConnectionInput = {
  name: string;
  description: string;
  secret: boolean;
  required: boolean;
};

const TRANSPORT_LABELS: Record<string, string> = {
  "streamable-http": "Streamable HTTP",
  sse: "Server-sent events",
  stdio: "Standard I/O",
};

const PACKAGE_REGISTRY_LABELS: Record<string, string> = {
  npm: "npm",
  pypi: "PyPI",
  oci: "Docker image",
  nuget: "NuGet",
  mcpb: "MCP bundle",
};

function hostOf(url: string | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

/** "vendor" | "agentarea" from the server facet, else from the spec itself. */
function connectionHosting(entry: CatalogEntry): CatalogHosting | null {
  if (entry.type !== "connections" || entry.protocol === "api") return null;
  if (isCatalogHosting(entry.hosting)) return entry.hosting;
  const ct = str(entry.spec.connection_type);
  if (ct === "command" || ct === "docker") return "agentarea";
  if (ct === "url" || str(entry.spec.url)) return "vendor";
  return null;
}

function inputsOf(entry: CatalogEntry): ConnectionInput[] {
  const seen = new Map<string, ConnectionInput>();
  const add = (raw: unknown) => {
    for (const f of arr(raw)) {
      const name = str(f.name);
      if (!name || seen.has(name)) continue;
      seen.set(name, {
        name,
        description: str(f.description) ?? "",
        secret: Boolean(f.isSecret ?? f.secret),
        required: Boolean(f.isRequired ?? f.required),
      });
    }
  };
  const spec = entry.spec;
  add(spec.env_schema);
  // The catalog publishes env_schema as a { NAME: field } map.
  const schema = spec.env_schema;
  if (schema && typeof schema === "object" && !Array.isArray(schema)) {
    add(
      Object.entries(schema as Record<string, RawSpec>).map(([name, f]) => ({
        ...f,
        name,
      }))
    );
  }
  const raw = spec.raw_spec as RawSpec | undefined;
  const url = str(spec.url);
  for (const r of arr(raw?.remotes)) {
    if (!url || str(r.url) === url) add(r.headers);
  }
  const pkg = spec.package as RawSpec | undefined;
  for (const p of arr(raw?.packages)) {
    if (!pkg || str(p.identifier) === str(pkg.identifier)) {
      add(p.environmentVariables);
    }
  }
  return [...seen.values()];
}

function ConnectionFacts({ entry }: { entry: CatalogEntry }) {
  const spec = entry.spec;
  const raw = (spec.raw_spec as RawSpec | undefined) ?? {};
  const meta = (raw.metadata as RawSpec | undefined) ?? {};
  const repo = str((raw.repository as RawSpec | undefined)?.url);
  const website = str(raw.websiteUrl);
  const publisher =
    repo?.match(/github\.com\/([^/]+)/i)?.[1] ??
    hostOf(website) ??
    str(raw.name)?.split("/")[0] ??
    null;
  const license = str(meta["agentarea:license"]);
  const audience = strArr(meta["agentarea:audience"]);
  const link = (href: string) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex max-w-full items-center gap-1 truncate text-primary hover:underline"
    >
      <span className="truncate">{href.replace(/^https?:\/\//, "")}</span>
      <ExternalLink className="h-3 w-3 shrink-0" />
    </a>
  );
  const facts: [string, React.ReactNode][] = [];
  if (publisher) facts.push(["Publisher", publisher]);
  if (repo) facts.push(["Source code", link(repo)]);
  if (website && website !== repo) facts.push(["Website", link(website)]);
  if (entry.category) facts.push(["Category", entry.category]);
  if (license)
    facts.push(["License", license === "NOASSERTION" ? "Not specified" : license]);
  if (audience.length)
    facts.push([
      "Available in",
      [...new Set(audience)].map((a) => a.toUpperCase()).join(", "),
    ]);
  const id = str(raw.name);
  if (id)
    facts.push([
      "Registry ID",
      <span key="id" className="font-mono text-xs text-muted-foreground">
        {id}
      </span>,
    ]);
  if (facts.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border border-border/60">
      <dl className="divide-y divide-border/60">
        {facts.map(([k, v]) => (
          <div key={k} className="flex gap-4 px-4 py-2.5 text-sm">
            <dt className="w-28 shrink-0 text-muted-foreground">{k}</dt>
            <dd className="min-w-0 truncate font-medium">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
    </div>
  );
}

function ConnectionHow({ entry }: { entry: CatalogEntry }) {
  const spec = entry.spec;
  const hosting = connectionHosting(entry);
  if (!hosting) return null;
  const transport = str(spec.transport);
  if (hosting === "vendor") {
    const url = str(spec.url);
    return (
      <div>
        <SectionLabel>How it connects</SectionLabel>
        <p className="text-sm">
          Hosted by {hostOf(url) ?? "the vendor"}. AgentArea calls their endpoint
          — nothing runs on our side.
        </p>
        {url && (
          <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {url}
            {transport ? ` · ${TRANSPORT_LABELS[transport] ?? transport}` : ""}
          </p>
        )}
      </div>
    );
  }
  const pkg = (spec.package as RawSpec | undefined) ?? {};
  const registry = str(pkg.registryType);
  const identifier = str(pkg.identifier) ?? str(spec.image);
  const command = [str(spec.command), ...strArr(spec.args)]
    .filter(Boolean)
    .join(" ");
  return (
    <div>
      <SectionLabel>How it connects</SectionLabel>
      <p className="text-sm">
        Runs on AgentArea: we start the server for your workspace from{" "}
        {registry ? (PACKAGE_REGISTRY_LABELS[registry] ?? registry) : "its package"}
        {identifier ? (
          <>
            {" "}
            <span className="font-mono text-xs">{identifier}</span>
          </>
        ) : null}
        .
      </p>
      {command && (
        <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
          $ {command}
        </p>
      )}
    </div>
  );
}

function ConnectionNeeds({ entry }: { entry: CatalogEntry }) {
  const inputs = inputsOf(entry);
  const raw = (entry.spec.raw_spec as RawSpec | undefined) ?? {};
  const meta = (raw.metadata as RawSpec | undefined) ?? {};
  const oauth =
    str(meta["agentarea:auth"]) === "oauth" ||
    Boolean(str(meta["agentarea:oauth_status"]));
  if (inputs.length === 0 && !oauth) return null;
  return (
    <div>
      <SectionLabel>What you will need</SectionLabel>
      <ul className="space-y-1.5">
        {oauth && (
          <li className="rounded bg-muted/50 px-3 py-2 text-sm">
            An account with the vendor — Connect asks you to sign in and approve
            access.
          </li>
        )}
        {inputs.map((f) => (
          <li
            key={f.name}
            className="flex flex-col gap-0.5 rounded bg-muted/50 px-3 py-2 text-sm"
          >
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs font-medium">{f.name}</span>
              {f.secret && (
                <Badge variant="light" size="sm">
                  secret
                </Badge>
              )}
              <span className="text-xs text-muted-foreground">
                {f.required ? "required" : "optional"}
              </span>
            </span>
            {f.description && (
              <span className="text-xs text-muted-foreground">
                {f.description}
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Misc ──

/** The element that scrolls the catalog: the nearest scrolling ancestor. */
function scrollContainerOf(el: HTMLElement | null): HTMLElement {
  for (let node = el?.parentElement; node; node = node.parentElement) {
    const { overflowY } = getComputedStyle(node);
    if (
      (overflowY === "auto" || overflowY === "scroll") &&
      node.scrollHeight > node.clientHeight
    ) {
      return node;
    }
  }
  return (document.scrollingElement as HTMLElement) ?? document.documentElement;
}

// Content placeholder that matches the selected view — grid of card-shaped
// skeletons or table rows — so switching type never shifts the layout.
function ContentSkeleton({ view }: { view: ViewMode }) {
  if (view === "table") return <CatalogTableSkeleton />;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {Array.from({ length: 10 }).map((_, i) => (
        <CatalogCardSkeleton key={i} />
      ))}
    </div>
  );
}

// Route-level skeleton for explore/loading.tsx. Mirrors the in-component `busy`
// layout (facet rail + search + content grid) so a hard refresh — where the SSR
// page is still awaiting its first fetch and React hasn't mounted the gallery
// yet — shows the same chrome-preserving skeleton instead of the generic
// full-screen spinner. Reads `type`/`view` from the URL so it matches the
// destination view exactly.
export function CatalogGallerySkeleton({
  initialView = "grid",
}: {
  initialView?: ViewMode;
}) {
  const [type] = useQueryState(
    "type",
    parseAsStringLiteral(TYPE_KEYS).withDefault("bundles")
  );
  // Match the view the page will actually restore (URL param > persisted cookie
  // > server-seeded default), read on the client via a lazy initializer. The
  // server seed alone is unreliable (a cached RSC / auth-gated SSR can serve a
  // stale default), which made the skeleton flash card placeholders while a
  // table view was loading. Reading the cookie here keeps the skeleton shape in
  // sync without a flash or a hydration mismatch (server + client agree on a
  // fresh load).
  const [view] = useState<ViewMode>(() => {
    if (typeof document === "undefined") return initialView;
    const fromUrl = new URLSearchParams(window.location.search).get("view");
    const saved = fromUrl ?? getCookie(EXPLORE_VIEW_COOKIE);
    return saved === "table" || saved === "grid" ? saved : initialView;
  });
  const t = useTranslations("CatalogPage.search");
  return (
    <div className="flex gap-6">
      <aside className="hidden w-52 shrink-0 lg:block">
        <FacetSkeleton />
      </aside>
      <div className="min-w-0 flex-1 space-y-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            disabled
            placeholder={t(type)}
            aria-hidden
            className="pl-9"
          />
        </div>
        <ContentSkeleton view={view} />
      </div>
    </div>
  );
}

// Mirrors CatalogCard: h-20 logo header + padded title/description body.
function CatalogCardSkeleton() {
  return (
    <div
      className="flex flex-col overflow-hidden rounded-lg border border-border/60 bg-white dark:border-zinc-700/60 dark:bg-zinc-900"
      aria-hidden="true"
    >
      <div className="flex h-20 items-center justify-center border-b border-border/40 bg-[radial-gradient(circle,theme(colors.zinc.200)_1px,transparent_1px)] [background-size:12px_12px] dark:bg-[radial-gradient(circle,theme(colors.zinc.800)_1px,transparent_1px)]">
        <div className="h-10 w-10 animate-pulse rounded-lg bg-muted" />
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
        <div className="h-3 w-full animate-pulse rounded bg-muted/60" />
        <div className="h-3 w-2/3 animate-pulse rounded bg-muted/60" />
      </div>
    </div>
  );
}

// Mirrors CATALOG_COLUMNS so the table does not shift when entries arrive.
const SKELETON_COLUMNS: Column<{ id: number }>[] = [
  {
    header: "Name",
    accessor: "title",
    headerClassName: "w-[40%] md:w-[32%]",
    render: () => (
      <div className="flex items-center gap-2.5">
        <div className="h-7 w-7 animate-pulse rounded-md bg-muted" />
        <div className="h-4 w-32 animate-pulse rounded bg-muted" />
      </div>
    ),
  },
  {
    header: "Category",
    accessor: "category",
    headerClassName: "hidden w-[200px] sm:table-cell",
    cellClassName: "hidden sm:table-cell",
    render: () => (
      <div className="h-4 w-24 animate-pulse rounded bg-muted/60" />
    ),
  },
  {
    header: "Description",
    accessor: "description",
    headerClassName: "hidden md:table-cell",
    cellClassName: "hidden md:table-cell",
    render: () => (
      <div className="h-3 w-64 animate-pulse rounded bg-muted/60" />
    ),
  },
];

function CatalogTableSkeleton() {
  return (
    <div aria-hidden="true">
      <Table
        className="table-fixed"
        data={Array.from({ length: 8 }, (_, id) => ({ id }))}
        columns={SKELETON_COLUMNS}
      />
    </div>
  );
}

// Back-button shell for the deep-link states (loading / not-found), so an
// ?item= link that isn't in the loaded page still shows chrome to return.
function DeepItemStatus({
  onBack,
  children,
}: {
  onBack: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Back to catalog
      </button>
      {children}
    </div>
  );
}

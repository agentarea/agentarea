"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Activity,
  ArrowDownAZ,
  Boxes,
  Check,
  Cloud,
  Cpu,
  Rows3,
} from "lucide-react";
import CollectionView, {
  CollectionFilterClear,
  CollectionFilterRow,
  CollectionSearchInput,
  CollectionSectionHeader,
  CollectionToolbar,
  StatusDot,
  type CollectionGroup,
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { cn } from "@/lib/utils";
import { setCookie } from "@/utils/cookies";
import { ProviderConfig, ProviderSpec } from "./types";

type ViewKey = "list" | "grid";
type TabKey = "all" | "cloud" | "local";
type GroupKey = "none" | "status" | "hosting";
type OrderKey = "name" | "status";

export interface ProviderModelsInitialState {
  view: ViewKey;
  tab: TabKey;
  group: GroupKey;
  order: OrderKey;
  search: string;
}

interface ProviderModelsViewProps {
  configs: ProviderConfig[];
  specs: ProviderSpec[];
  initial: ProviderModelsInitialState;
}

/* AgentArea brand blue — drives the tile tint + accent model pills. */
const ACCENT = "#2252b3";

/* ── hosting + status ──────────────────────────────────────────────────── */

const LOCAL_PROVIDER_KEYS = new Set([
  "ollama",
  "vllm",
  "lmstudio",
  "lm_studio",
  "localai",
  "local_ai",
  "llamacpp",
  "llama_cpp",
  "local",
]);

/** Self-hosted providers run on the user's own infrastructure. */
function isLocalHosting(
  key?: string | null,
  type?: string | null,
  endpoint?: string | null
): boolean {
  const k = (key ?? "").toLowerCase();
  const t = (type ?? "").toLowerCase();
  if (LOCAL_PROVIDER_KEYS.has(k) || LOCAL_PROVIDER_KEYS.has(t)) return true;
  if (t.includes("local") || t.includes("self")) return true;
  if (endpoint && /localhost|127\.0\.0\.1|0\.0\.0\.0/.test(endpoint)) return true;
  return false;
}

/* config status buckets — dot + label colour, drives the chip, grouping +
   ordering. We only surface states the data can actually prove. */
type StatusKey = "active" | "local" | "inactive";
const STATUS_BUCKETS: { key: StatusKey; color: string }[] = [
  { key: "active", color: "#1f9a6d" },
  { key: "local", color: "#27a08c" },
  { key: "inactive", color: "#8a8f98" },
];

function statusMeta(key: StatusKey) {
  return STATUS_BUCKETS.find((b) => b.key === key) ?? STATUS_BUCKETS[2];
}

function configStatus(config: ProviderConfig, local: boolean): StatusKey {
  if (local) return "local";
  return config.is_active ? "active" : "inactive";
}

/* ── small presentational pieces (match the prototype) ─────────────────── */

const STATUS_LABEL_KEY: Record<StatusKey, string> = {
  active: "statusActive",
  local: "statusLocal",
  inactive: "statusInactive",
};

/** Maps a config status into the shared StatusDot (dot + colour-matched label). */
function ConfigStatusDot({ status }: { status: StatusKey }) {
  const t = useTranslations("Models.view");
  const s = statusMeta(status);
  return <StatusDot color={s.color} label={t(STATUS_LABEL_KEY[status])} />;
}

/** Mono accent pill, e.g. `gpt-4o`. */
function ModelTag({ label, more }: { label: string; more?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 max-w-[150px] shrink-0 items-center truncate rounded-md px-2 text-[11px] font-medium",
        more
          ? "bg-muted font-sans text-muted-foreground"
          : "font-mono text-primary"
      )}
      style={more ? undefined : { background: `color-mix(in srgb, ${ACCENT} 9%, var(--tile-base))` }}
    >
      {label}
    </span>
  );
}

/** Up to `max` model pills, fading out under a mask, then a `+N` overflow tag. */
function ModelTags({ models, max = 2 }: { models: string[]; max?: number }) {
  if (models.length === 0) return null;
  const shown = models.slice(0, max);
  return (
    <span
      className="flex min-w-0 items-center gap-1.5 overflow-hidden"
      style={{
        maskImage: "linear-gradient(90deg, #000 86%, transparent)",
        WebkitMaskImage: "linear-gradient(90deg, #000 86%, transparent)",
      }}
    >
      {shown.map((m, i) => (
        <ModelTag key={i} label={m} />
      ))}
      {models.length > max && <ModelTag label={`+${models.length - max}`} more />}
    </span>
  );
}

/** Inline `N models` / `Self-host` label. */
function ModelCountText({ count, selfHost }: { count: number; selfHost?: boolean }) {
  const t = useTranslations("Models.view");
  return (
    <span className="whitespace-nowrap text-[11.5px] text-muted-foreground">
      {selfHost ? (
        t("selfHost")
      ) : (
        <>
          <span className="font-mono font-semibold text-foreground/80">{count}</span>{" "}
          {t("modelWord", { count })}
        </>
      )}
    </span>
  );
}

/* ── helpers ───────────────────────────────────────────────────────────── */

function modelLabel(model: any, unknown: string): string {
  return (
    model.model_display_name ||
    model.display_name ||
    model.model_name ||
    model.name ||
    unknown
  );
}

function providerIcon(iconUrl?: string | null): CollectionItem["icon"] {
  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt=""
        aria-hidden="true"
        className="h-4 w-4 rounded object-contain dark:invert"
      />
    );
  }
  return Cpu;
}

/* ── view ──────────────────────────────────────────────────────────────── */

export default function ProviderModelsView({
  configs,
  specs,
  initial,
}: ProviderModelsViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const tc = useTranslations("Collection");
  const t = useTranslations("Models.view");

  const [view, setView] = useState<ViewKey>(initial.view);
  const [tab, setTab] = useState<TabKey>(initial.tab);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [search, setSearch] = useState(initial.search);
  const [filtersOpen, setFiltersOpen] = useState(Boolean(initial.search));
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  // ── URL sync ──
  const syncUrl = useCallback(
    (next: Partial<ProviderModelsInitialState>) => {
      const merged = { view, tab, group, order, search, ...next };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "grid");
      set("hosting", merged.tab, "all");
      set("group", merged.group, "none");
      set("order", merged.order, "name");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [view, tab, group, order, search, searchParams, router, pathname]
  );

  // ── config entries (Provider configs) ──
  type ConfigEntry = {
    item: CollectionItem;
    local: boolean;
    status: StatusKey;
    name: string;
    text: string;
  };

  const configEntries = useMemo<ConfigEntry[]>(
    () =>
      configs.map((config): ConfigEntry => {
        const spec = config.spec;
        const local = isLocalHosting(
          spec?.provider_key ?? config.provider_spec_key,
          spec?.provider_type,
          config.endpoint_url
        );
        const status = configStatus(config, local);
        const instances = config.model_instances ?? [];
        const modelNames = instances.map((m) => modelLabel(m, t("unknownModel")));
        const count = instances.length;
        const providerName =
          config.provider_spec_name ?? spec?.name ?? "";
        return {
          local,
          status,
          name: config.name,
          text: `${config.name} ${providerName} ${modelNames.join(" ")}`.toLowerCase(),
          item: {
            id: config.id,
            color: ACCENT,
            icon: providerIcon(spec?.icon_url),
            title: config.name,
            href: `/admin/provider-configs/edit/${config.id}`,
            // provider shown as the muted secondary text right after the name,
            // in the first column (like /skills); the right cluster keeps the
            // model tags · status · count.
            description: providerName || null,
            hideDescription: true,
            cardSubtitle: providerName || null,
            metaPlain: true,
            meta: (
              <span className="collection-hide-mobile flex items-center gap-3">
                <span className="collection-col-source flex max-w-[190px] overflow-hidden">
                  <ModelTags models={modelNames} max={2} />
                </span>
                <ConfigStatusDot status={status} />
                <ModelCountText count={count} />
              </span>
            ),
            cardFooter: (
              <div className="flex items-center gap-2 pr-6">
                <ModelCountText count={count} />
                <span className="flex-1" />
                <ConfigStatusDot status={status} />
              </div>
            ),
          },
        };
      }),
    [configs, t]
  );

  // ── spec items (Provider specs) ──
  type SpecEntry = {
    item: CollectionItem;
    local: boolean;
    name: string;
    text: string;
  };

  const specEntries = useMemo<SpecEntry[]>(
    () =>
      specs.map((spec): SpecEntry => {
        const local = isLocalHosting(spec.provider_key, spec.provider_type, null);
        const count = (spec.models ?? []).length;
        return {
          local,
          name: spec.name,
          text: `${spec.name} ${spec.provider_key ?? ""} ${
            spec.description ?? ""
          }`.toLowerCase(),
          item: {
            id: spec.id,
            color: ACCENT,
            icon: providerIcon(spec.icon_url),
            title: spec.name,
            href: `/admin/provider-configs/create/${spec.id}`,
            // description shown right after the name in the first column
            // (like /skills); the right cluster keeps the model count.
            description: spec.description,
            compactDescription: true,
            metaPlain: true,
            meta: (
              <span className="collection-hide-mobile">
                <ModelCountText count={count} selfHost={local} />
              </span>
            ),
            cardFooter: (
              <div className="flex items-center gap-2 pr-6">
                <ModelCountText count={count} selfHost={local} />
              </div>
            ),
          },
        };
      }),
    [specs]
  );

  // ── filtering ──
  const q = search.trim().toLowerCase();
  const matchesTab = useCallback(
    (local: boolean) =>
      tab === "all" || (tab === "local" ? local : !local),
    [tab]
  );

  const visibleConfigs = useMemo(
    () =>
      configEntries.filter(
        (e) => matchesTab(e.local) && (!q || e.text.includes(q))
      ),
    [configEntries, matchesTab, q]
  );
  const visibleSpecs = useMemo(
    () =>
      specEntries.filter(
        (e) => matchesTab(e.local) && (!q || e.text.includes(q))
      ),
    [specEntries, matchesTab, q]
  );

  const sortConfigs = useCallback(
    (arr: ConfigEntry[]) => {
      const out = [...arr];
      if (order === "status") {
        const rank = (e: ConfigEntry) =>
          STATUS_BUCKETS.findIndex((b) => b.key === e.status);
        out.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
      } else {
        out.sort((a, b) => a.name.localeCompare(b.name));
      }
      return out;
    },
    [order]
  );

  // ── "Provider configs" body: groups (list + grouping) or flat items ──
  const configGroups = useMemo<CollectionGroup[] | undefined>(() => {
    if (view !== "list" || group === "none") return undefined;
    if (group === "hosting") {
      return [
        { key: "cloud", label: t("groupCloud"), color: ACCENT, local: false },
        { key: "local", label: t("groupSelfHosted"), color: "#27a08c", local: true },
      ]
        .map((g) => ({
          key: g.key,
          label: g.label,
          color: g.color,
          items: sortConfigs(
            visibleConfigs.filter((e) => e.local === g.local)
          ).map((e) => e.item),
        }))
        .filter((g) => g.items.length > 0);
    }
    return STATUS_BUCKETS.map((b) => ({
      key: b.key,
      label: t(STATUS_LABEL_KEY[b.key]),
      color: b.color,
      items: sortConfigs(visibleConfigs.filter((e) => e.status === b.key)).map(
        (e) => e.item
      ),
    })).filter((g) => g.items.length > 0);
  }, [view, group, visibleConfigs, sortConfigs, t]);

  const configItems = useMemo(
    () => sortConfigs(visibleConfigs).map((e) => e.item),
    [visibleConfigs, sortConfigs]
  );
  const visibleSpecItems = useMemo(
    () => visibleSpecs.map((e) => e.item),
    [visibleSpecs]
  );

  // ── tab counts (configs, per the design) ──
  const counts = useMemo(() => {
    const local = configEntries.filter((e) => e.local).length;
    return {
      all: configEntries.length,
      cloud: configEntries.length - local,
      local,
    };
  }, [configEntries]);

  // ── control handlers ──
  const onTab = (v: string) => {
    setTab(v as TabKey);
    syncUrl({ tab: v as TabKey });
  };
  const onView = (v: ViewKey) => {
    setView(v);
    setCookie("view_admin_provider-configs", v);
    syncUrl({ view: v });
  };
  const onGroup = (v: string) => {
    setGroup(v as GroupKey);
    syncUrl({ group: v as GroupKey });
  };
  const onOrder = (v: string) => {
    setOrder(v as OrderKey);
    syncUrl({ order: v as OrderKey });
  };
  const onSearch = (v: string) => {
    setSearch(v);
    syncUrl({ search: v });
  };
  const toggle = (key: string) =>
    setCollapsed((p) => ({ ...p, [key]: !p[key] }));

  const isEmpty = configs.length === 0 && specs.length === 0;

  return (
    <div className="collection-cq flex h-full w-full flex-col">
      <CollectionToolbar
        tabs={[
          { value: "all", label: tc("all"), count: counts.all },
          { value: "cloud", label: tc("cloud"), count: counts.cloud },
          { value: "local", label: tc("selfHosted"), count: counts.local },
        ]}
        activeTab={tab}
        onTabChange={onTab}
        filterActive={filtersOpen}
        onToggleFilter={() => setFiltersOpen((v) => !v)}
        groupOptions={[
          { value: "none", label: tc("noGrouping"), icon: <Rows3 className="h-3.5 w-3.5" /> },
          { value: "status", label: tc("status"), icon: <Activity className="h-3.5 w-3.5" /> },
          { value: "hosting", label: tc("hosting"), icon: <Cloud className="h-3.5 w-3.5" /> },
        ]}
        group={group}
        onGroupChange={onGroup}
        orderOptions={[
          { value: "name", label: tc("name"), icon: <ArrowDownAZ className="h-3.5 w-3.5" /> },
          { value: "status", label: tc("status"), icon: <Activity className="h-3.5 w-3.5" /> },
        ]}
        order={order}
        onOrderChange={onOrder}
        view={view}
        onViewChange={(v) => onView(v as ViewKey)}
      />

      {filtersOpen && (
        <CollectionFilterRow>
          <CollectionSearchInput value={search} onChange={onSearch} />
          {search && <CollectionFilterClear onClick={() => onSearch("")} />}
        </CollectionFilterRow>
      )}

      <div className="min-h-0 flex-1 overflow-auto">
        {isEmpty ? (
          <div className="p-4">
            <EmptyState
              title={t("emptyTitle")}
              description={t("emptyDescription")}
              iconsType="llm"
            />
          </div>
        ) : (
          <>
            {/* SECTION 1 — Provider configs */}
            <CollectionSectionHeader
              icon={<Check className="h-3 w-3" strokeWidth={2.4} />}
              name={t("configsSection")}
              count={visibleConfigs.length}
              sub={t("configsSub")}
              variant={view}
              collapsed={!!collapsed.configs}
              onToggle={() => toggle("configs")}
            />
            {(view === "grid" || !collapsed.configs) && (
              <CollectionView
                view={view}
                containerQuery={false}
                gridClassName="px-4 pb-4"
                gridMinWidth={230}
                groups={configGroups}
                items={configGroups ? undefined : configItems}
                emptyState={
                  <div className="px-4 py-3 text-[12px] text-muted-foreground">
                    {search ? t("noConfigsMatch") : t("noConfigsYet")}
                  </div>
                }
              />
            )}

            {/* SECTION 2 — Provider specs */}
            <CollectionSectionHeader
              icon={<Boxes className="h-3 w-3" strokeWidth={2} />}
              name={t("specsSection")}
              count={visibleSpecItems.length}
              sub={t("specsSub")}
              variant={view}
              collapsed={!!collapsed.specs}
              onToggle={() => toggle("specs")}
            />
            {(view === "grid" || !collapsed.specs) && (
              <CollectionView
                view={view}
                containerQuery={false}
                gridClassName="px-4 pb-4"
                gridMinWidth={230}
                items={visibleSpecItems}
                emptyState={
                  <div className="px-4 py-3 text-[12px] text-muted-foreground">
                    {t("noProvidersMatch")}
                  </div>
                }
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}

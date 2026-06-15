"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowDownAZ,
  ChevronDown,
  Clock,
  Filter,
  Inbox,
  Layers,
  Rows3,
  SlidersHorizontal,
  Tag,
  X,
} from "lucide-react";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import EmptyState from "@/components/EmptyState";
import HeaderTabs from "@/components/HeaderTabs";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listSkillsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import type { PaginatedSkills, Skill } from "@/types/skill";
import { setCookie } from "@/utils/cookies";
import { getValidTimestamp } from "@/utils/dateUtils";
import SkillRow from "./SkillRow";
import SkillsCard from "./SkillsCard";
import {
  SCOPE_META,
  SCOPE_ORDER,
  scopeMeta,
  SOURCE_ORDER,
  sourceMeta,
} from "./skillsMeta";

type GroupKey = "source" | "scope" | "none";
type OrderKey = "name" | "created";
type ViewKey = "list" | "grid";

interface InitialState {
  view: ViewKey;
  group: GroupKey;
  order: OrderKey;
  sourceTab: string; // "all" | content | github | zip | path
  scope: string; // "" | private | ingress | egress
  files: string; // all | with_files | without_files
  search: string;
}

const SOURCE_TABS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "content", label: "Content" },
  { value: "github", label: "GitHub" },
  { value: "zip", label: "Uploaded" },
  { value: "path", label: "Local" },
];

async function fetchAllSkills(): Promise<Skill[]> {
  const all: Skill[] = [];
  let page = 1;
  // Linear-style grouping needs the full set; page through with a hard cap.
  for (; page <= 20; page++) {
    const { data } = await listSkillsAction({
      page,
      page_size: 100,
      paginated: true,
      // Only your own skills here — the registry/catalog lives in Explore.
      from_registry: false,
    });
    const res = data as PaginatedSkills | null;
    if (!res?.items?.length) break;
    all.push(...res.items);
    if (!res.has_next) break;
  }
  return all;
}

export default function SkillsView({ initial }: { initial: InitialState }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const t = useTranslations("SkillsPage");

  const [skills, setSkills] = useState<Skill[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  // view/grouping state (URL-shareable)
  const [view, setView] = useState<ViewKey>(initial.view);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [sourceTab, setSourceTab] = useState(initial.sourceTab);
  const [scope, setScope] = useState(initial.scope);
  const [files, setFiles] = useState(initial.files);
  const [search, setSearch] = useState(initial.search);

  // local-only UI state
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  const [filtersOpen, setFiltersOpen] = useState(
    Boolean(initial.scope) || initial.files !== "all"
  );

  useEffect(() => {
    let active = true;
    setIsLoading(true);
    setError(false);
    fetchAllSkills()
      .then((items) => active && setSkills(items))
      .catch(() => active && setError(true))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, []);

  // Sync the shareable bits of state into the URL without a navigation.
  const syncUrl = useCallback(
    (next: Partial<InitialState>) => {
      const merged: InitialState = {
        view,
        group,
        order,
        sourceTab,
        scope,
        files,
        search,
        ...next,
      };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "list");
      set("group", merged.group, "source");
      set("order", merged.order, "name");
      set("source_type", merged.sourceTab, "all");
      set("network_scope", merged.scope, "");
      set("files", merged.files, "all");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [
      view,
      group,
      order,
      sourceTab,
      scope,
      files,
      search,
      searchParams,
      router,
      pathname,
    ]
  );

  const toggleFavorite = useCallback((id: string) => {
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleGroup = useCallback((key: string) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // Apply the non-tab filters (scope / files / search) — drives tab counts too.
  const baseFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return skills.filter((s) => {
      if (scope && s.network_scope !== scope) return false;
      if (files === "with_files" && !s.has_files) return false;
      if (files === "without_files" && s.has_files) return false;
      if (q) {
        const hay = `${s.name} ${s.description ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [skills, scope, files, search]);

  const tabCounts = useMemo(() => {
    const counts: Record<string, number> = { all: baseFiltered.length };
    for (const s of baseFiltered) {
      counts[s.source_type] = (counts[s.source_type] ?? 0) + 1;
    }
    return counts;
  }, [baseFiltered]);

  const visible = useMemo(
    () =>
      sourceTab === "all"
        ? baseFiltered
        : baseFiltered.filter((s) => s.source_type === sourceTab),
    [baseFiltered, sourceTab]
  );

  const sortItems = useCallback(
    (arr: Skill[]) => {
      const out = [...arr];
      if (order === "name") {
        out.sort((a, b) => a.name.localeCompare(b.name));
      } else {
        out.sort(
          (a, b) =>
            (getValidTimestamp(b.created_at) ?? 0) -
            (getValidTimestamp(a.created_at) ?? 0)
        );
      }
      return out;
    },
    [order]
  );

  const groups = useMemo(() => {
    if (group === "none") {
      return [{ key: "none", label: "", color: "", items: sortItems(visible) }];
    }
    const order_ = group === "source" ? SOURCE_ORDER : SCOPE_ORDER;
    const meta = group === "source" ? sourceMeta : scopeMeta;
    const field: keyof Skill =
      group === "source" ? "source_type" : "network_scope";
    return order_
      .map((key) => {
        const items = sortItems(visible.filter((s) => s[field] === key));
        const m = meta(key);
        return { key, label: m.label, color: m.color, items };
      })
      .filter((g) => g.items.length > 0);
  }, [group, visible, sortItems]);

  const hasActiveFilters =
    Boolean(scope) || files !== "all" || Boolean(search) || sourceTab !== "all";

  // ---- toolbar control helpers ----
  const onTab = (value: string) => {
    setSourceTab(value);
    syncUrl({ sourceTab: value });
  };
  const onView = (value: ViewKey) => {
    setView(value);
    setCookie("view_skills", value);
    syncUrl({ view: value });
  };
  const onGroup = (value: GroupKey) => {
    setGroup(value);
    syncUrl({ group: value });
  };
  const onOrder = (value: OrderKey) => {
    setOrder(value);
    syncUrl({ order: value });
  };
  const onScope = (value: string) => {
    const v = value === "all" ? "" : value;
    setScope(v);
    syncUrl({ scope: v });
  };
  const onFiles = (value: string) => {
    setFiles(value);
    syncUrl({ files: value });
  };
  const onSearch = (value: string) => {
    setSearch(value);
    syncUrl({ search: value });
  };
  const clearFilters = () => {
    setScope("");
    setFiles("all");
    setSearch("");
    setSourceTab("all");
    syncUrl({ scope: "", files: "all", search: "", sourceTab: "all" });
  };

  return (
    <div className="skills-cq flex h-full w-full flex-col">
      {/* ---------------- toolbar ---------------- */}
      <div className="flex h-[42px] shrink-0 items-center gap-1.5 border-b border-zinc-200 px-4 dark:border-zinc-700">
        {/* source tabs — scroll horizontally when the panel is narrow so the
            right-hand controls always stay visible */}
        <div className="no-scrollbar flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {SOURCE_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => onTab(tab.value)}
              className={cn(
                "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-medium transition-colors",
                sourceTab === tab.value
                  ? "bg-muted text-foreground"
                  : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
              )}
            >
              {tab.label}
              <span className="text-[11px] text-muted-foreground/70">
                {tabCounts[tab.value] ?? 0}
              </span>
            </button>
          ))}
        </div>

        <div className="mx-1 h-[18px] w-px shrink-0 bg-zinc-200 dark:bg-zinc-700" />

        {/* Filter toggle */}
        <button
          type="button"
          onClick={() => setFiltersOpen((v) => !v)}
          className={cn(
            "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal transition-colors",
            filtersOpen
              ? "bg-muted text-foreground"
              : "text-foreground/80 hover:bg-muted/60"
          )}
        >
          <Filter className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="skills-btn-label">{t("filters.filter")}</span>
        </button>

        {/* Display menu */}
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal text-foreground/80 transition-colors hover:bg-muted/60"
            >
              <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="skills-btn-label">{t("display.display")}</span>
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-52 p-1.5">
            <p className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
              {t("display.grouping")}
            </p>
            <MenuRow
              icon={<Layers className="h-3.5 w-3.5" />}
              label={t("display.source")}
              selected={group === "source"}
              onClick={() => onGroup("source")}
            />
            <MenuRow
              icon={<Tag className="h-3.5 w-3.5" />}
              label={t("display.scope")}
              selected={group === "scope"}
              onClick={() => onGroup("scope")}
            />
            <MenuRow
              icon={<Rows3 className="h-3.5 w-3.5" />}
              label={t("display.none")}
              selected={group === "none"}
              onClick={() => onGroup("none")}
            />
            <div className="my-1 h-px bg-border" />
            <p className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/70">
              {t("display.ordering")}
            </p>
            <MenuRow
              icon={<ArrowDownAZ className="h-3.5 w-3.5" />}
              label={t("display.name")}
              selected={order === "name"}
              onClick={() => onOrder("name")}
            />
            <MenuRow
              icon={<Clock className="h-3.5 w-3.5" />}
              label={t("display.created")}
              selected={order === "created"}
              onClick={() => onOrder("created")}
            />
          </PopoverContent>
        </Popover>

        {/* list / grid segment */}
        <HeaderTabs
          className="ml-1 shrink-0"
          value={view}
          onChange={(v) => onView(v as ViewKey)}
          tabs={[
            { value: "list", label: "List view" },
            { value: "grid", label: "Grid view" },
          ]}
        />
      </div>

      {/* ---------------- applied filter row ---------------- */}
      {filtersOpen && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-zinc-200 px-3.5 py-2 dark:border-zinc-700">
          <FilterSelect
            value={scope || "all"}
            placeholder={t("filters.scope")}
            active={Boolean(scope)}
            onValueChange={onScope}
          >
            <SelectItem value="all">{t("filters.allScopes")}</SelectItem>
            {SCOPE_ORDER.map((s) => (
              <SelectItem key={s} value={s}>
                {SCOPE_META[s].label}
              </SelectItem>
            ))}
          </FilterSelect>
          <FilterSelect
            value={files}
            placeholder={t("filters.files")}
            active={files !== "all"}
            onValueChange={onFiles}
          >
            <SelectItem value="all">{t("filters.allFiles")}</SelectItem>
            <SelectItem value="with_files">{t("filters.withFiles")}</SelectItem>
            <SelectItem value="without_files">
              {t("filters.withoutFiles")}
            </SelectItem>
          </FilterSelect>
          <div className="relative">
            <input
              value={search}
              onChange={(e) => onSearch(e.target.value)}
              placeholder={t("searchPlaceholder")}
              className="h-6 w-44 rounded-md border border-border bg-background px-2 text-xs outline-none focus:border-primary"
            />
          </div>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={clearFilters}
              className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-xs text-muted-foreground hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
              {t("filters.clear")}
            </button>
          )}
        </div>
      )}

      {/* ---------------- body ---------------- */}
      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        ) : error ? (
          <div className="flex h-64 items-center justify-center text-destructive">
            {t("error.loadSkills")}
          </div>
        ) : skills.length === 0 ? (
          <div className="space-y-4 p-4">
            <EmptyState
              title={t("noSkills")}
              description={t("noSkillsDescription")}
              iconsType="skills"
              action={{
                label: t("addSkill"),
                onClick: () => router.push("/skills/create"),
              }}
            />
            <CatalogSuggestions type="skills" />
          </div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-1.5 py-24 text-muted-foreground">
            <Inbox className="h-6 w-6" />
            <p className="text-sm font-semibold text-foreground">
              {t("emptyHere")}
            </p>
            <p className="text-xs">{t("emptyHereDescription")}</p>
          </div>
        ) : view === "grid" ? (
          <div
            className="grid gap-3 p-4"
            style={{
              gridTemplateColumns: "repeat(auto-fill, minmax(264px, 1fr))",
            }}
          >
            {sortItems(visible).map((skill) => (
              <SkillsCard
                key={skill.id}
                skill={skill}
                isFavorite={favorites.has(skill.id)}
                onToggleFavorite={toggleFavorite}
              />
            ))}
          </div>
        ) : (
          <div>
            {groups.map((g) => (
              <div key={g.key}>
                {group !== "none" && (
                  <button
                    type="button"
                    onClick={() => toggleGroup(g.key)}
                    className="skill-hatch sticky top-0 z-[2] flex h-9 w-full items-center gap-2 border-b border-zinc-100 px-4 dark:border-zinc-800/70"
                  >
                    <ChevronDown
                      className={cn(
                        "h-3.5 w-3.5 text-muted-foreground transition-transform",
                        collapsed[g.key] && "-rotate-90"
                      )}
                    />
                    <span
                      className="h-[9px] w-[9px] rounded-[3px]"
                      style={{ backgroundColor: g.color }}
                    />
                    <span className="text-[12.5px] font-semibold">
                      {g.label}
                    </span>
                    <span className="rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] text-muted-foreground">
                      {g.items.length}
                    </span>
                  </button>
                )}
                {!collapsed[g.key] &&
                  g.items.map((skill) => (
                    <SkillRow
                      key={skill.id}
                      skill={skill}
                      isFavorite={favorites.has(skill.id)}
                      onToggleFavorite={toggleFavorite}
                    />
                  ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MenuRow({
  icon,
  label,
  selected,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[12.5px]",
        selected ? "text-primary" : "text-foreground/80 hover:bg-muted"
      )}
    >
      <span className={selected ? "text-primary" : "text-muted-foreground"}>
        {icon}
      </span>
      {label}
    </button>
  );
}

function FilterSelect({
  value,
  placeholder,
  active,
  onValueChange,
  children,
}: {
  value: string;
  placeholder: string;
  active: boolean;
  onValueChange: (v: string) => void;
  children: React.ReactNode;
}) {
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        className={cn(
          "h-6 w-auto gap-1.5 rounded-md border border-border bg-background px-2 text-xs font-normal shadow-none focus:ring-0",
          active ? "font-medium text-foreground" : "text-muted-foreground"
        )}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

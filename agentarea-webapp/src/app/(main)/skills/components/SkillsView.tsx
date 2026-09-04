"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowDownAZ,
  Clock,
  Inbox,
  Layers,
  Rows3,
  Tag,
} from "lucide-react";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import DisplayMenu from "@/components/DisplayMenu/DisplayMenu";
import EmptyState from "@/components/EmptyState";
import HeaderTabs from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import { GroupHeader } from "@/components/ui/group-header";
import { listSkillsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import type { PaginatedSkills, Skill } from "@/types/skill";
import { setCookie } from "@/utils/cookies";
import { getValidTimestamp } from "@/utils/dateUtils";
import SkillRow from "./SkillRow";
import SkillsCard from "./SkillsCard";
import SkillsContentSkeleton from "./SkillsContentSkeleton";
import {
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
  search: string;
}

const SOURCE_TABS: { value: string; label: string }[] = [
  { value: "all", label: "All" },
  { value: "content", label: "Content" },
  { value: "github", label: "GitHub" },
  { value: "zip", label: "Uploaded" },
  { value: "path", label: "Local" },
];

// Source tabs duplicate the Filters + Display grouping already on this page and
// stay mostly empty in practice, so they're hidden for now. Flip to re-enable —
// all the backing state/logic is kept intact below.
const SHOW_SOURCE_TABS = false;

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
  const [scope] = useState(initial.scope);
  const [search, setSearch] = useState(initial.search);

  // local-only UI state
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

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

  // Apply the non-tab filters (scope / search) — drives tab counts too.
  const baseFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return skills.filter((s) => {
      if (scope && s.network_scope !== scope) return false;
      if (q) {
        const hay = `${s.name} ${s.description ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [skills, scope, search]);

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
  const onSearch = useCallback((value: string) => {
    setSearch(value);
  }, []);

  return (
    <div className="skills-cq flex h-full w-full flex-col">
      {/* ---------------- toolbar ---------------- */}
      <div className="flex h-[42px] shrink-0 items-center gap-1.5 border-b border-zinc-200 px-4 dark:border-zinc-700">
        {/* source tabs — scroll horizontally when the panel is narrow so the
            right-hand controls always stay visible */}
        {SHOW_SOURCE_TABS ? (
          <>
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
          </>
        ) : (
          <div className="min-w-0 flex-1">
            <SearchInput
              urlParamName="search"
              urlPath="/skills"
              onDebouncedChange={onSearch}
            />
          </div>
        )}

        {/* Display menu */}
        <DisplayMenu
          label={t("display.display")}
          labelClassName="skills-btn-label"
          sections={[
            {
              key: "grouping",
              label: t("display.grouping"),
              items: [
                {
                  key: "source",
                  icon: <Layers className="h-3.5 w-3.5" />,
                  label: t("display.source"),
                  selected: group === "source",
                  onSelect: () => onGroup("source"),
                },
                {
                  key: "scope",
                  icon: <Tag className="h-3.5 w-3.5" />,
                  label: t("display.scope"),
                  selected: group === "scope",
                  onSelect: () => onGroup("scope"),
                },
                {
                  key: "none",
                  icon: <Rows3 className="h-3.5 w-3.5" />,
                  label: t("display.none"),
                  selected: group === "none",
                  onSelect: () => onGroup("none"),
                },
              ],
            },
            {
              key: "ordering",
              label: t("display.ordering"),
              items: [
                {
                  key: "name",
                  icon: <ArrowDownAZ className="h-3.5 w-3.5" />,
                  label: t("display.name"),
                  selected: order === "name",
                  onSelect: () => onOrder("name"),
                },
                {
                  key: "created",
                  icon: <Clock className="h-3.5 w-3.5" />,
                  label: t("display.created"),
                  selected: order === "created",
                  onSelect: () => onOrder("created"),
                },
              ],
            },
          ]}
        />

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

      {/* ---------------- body ---------------- */}
      <div className="min-h-0 flex-1 overflow-auto">
        {isLoading ? (
          <SkillsContentSkeleton view={view} />
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
                  <GroupHeader
                    label={g.label}
                    count={g.items.length}
                    color={g.color}
                    collapsed={collapsed[g.key]}
                    onToggle={() => toggleGroup(g.key)}
                  />
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

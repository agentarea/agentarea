"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowDownAZ, Clock, Copy, Inbox, Layers, Rows3, Star, Tag } from "lucide-react";
import CollectionView, {
  CollectionFilterClear,
  CollectionFilterRow,
  CollectionSearchInput,
  CollectionToolbar,
  FilterSelect,
  type CollectionGroup,
  type CollectionItem,
  shortAge,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { SelectItem } from "@/components/ui/select";
import { listSkillsAction } from "@/lib/server-actions";
import type { PaginatedSkills, Skill } from "@/types/skill";
import { setCookie } from "@/utils/cookies";
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

const SOURCE_TABS: { value: string; labelKey?: string }[] = [
  { value: "all" },
  { value: "content", labelKey: "sourceContent" },
  { value: "github", labelKey: "sourceGithub" },
  { value: "zip", labelKey: "sourceUploaded" },
  { value: "path", labelKey: "sourceLocal" },
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
  const tv = useTranslations("SkillsPage.view");
  const tc = useTranslations("Collection");

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
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
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
        return { key, label: tv(m.labelKey), color: m.color, items };
      })
      .filter((g) => g.items.length > 0);
  }, [group, visible, sortItems, tv]);

  // Adapt a skill into the generic CollectionView item shape. Favourite +
  // duplicate are supplied as hover quick-actions.
  const toItem = useCallback(
    (skill: Skill): CollectionItem => {
      const source = sourceMeta(skill.source_type);
      const scope = scopeMeta(skill.network_scope);
      const isFav = favorites.has(skill.id);
      return {
        id: skill.id,
        icon: source.icon,
        color: source.color,
        title: skill.name,
        description: skill.description,
        href: `/skills/${skill.id}`,
        badges: [
          { label: tv(source.labelKey), color: source.color },
          { label: tv(scope.labelKey), icon: scope.icon },
        ],
        meta: shortAge(skill.created_at, tc),
        actions: [
          {
            icon: Star,
            label: isFav ? tv("removeFavorite") : tv("addFavorite"),
            active: isFav,
            activeColor: "#d99a00",
            onClick: () => toggleFavorite(skill.id),
          },
          {
            icon: Copy,
            label: tv("duplicate"),
            onClick: () => router.push(`/skills/create?from=${skill.id}`),
          },
        ],
      };
    },
    [favorites, toggleFavorite, router, tv, tc]
  );

  const collectionGroups: CollectionGroup[] = useMemo(
    () =>
      groups.map((g) => ({
        key: g.key,
        label: g.label,
        color: g.color,
        items: g.items.map(toItem),
      })),
    [groups, toItem]
  );

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
    <div className="collection-cq flex h-full w-full flex-col">
      <CollectionToolbar
        tabs={SOURCE_TABS.map((tab) => ({
          value: tab.value,
          label: tab.labelKey ? tv(tab.labelKey) : tc("all"),
          count: tabCounts[tab.value] ?? 0,
        }))}
        activeTab={sourceTab}
        onTabChange={onTab}
        filterLabel={t("filters.filter")}
        filterActive={filtersOpen}
        onToggleFilter={() => setFiltersOpen((v) => !v)}
        displayLabel={t("display.display")}
        groupingLabel={t("display.grouping")}
        groupOptions={[
          {
            value: "source",
            label: t("display.source"),
            icon: <Layers className="h-3.5 w-3.5" />,
          },
          {
            value: "scope",
            label: t("display.scope"),
            icon: <Tag className="h-3.5 w-3.5" />,
          },
          {
            value: "none",
            label: t("display.none"),
            icon: <Rows3 className="h-3.5 w-3.5" />,
          },
        ]}
        group={group}
        onGroupChange={(v) => onGroup(v as GroupKey)}
        orderingLabel={t("display.ordering")}
        orderOptions={[
          {
            value: "name",
            label: t("display.name"),
            icon: <ArrowDownAZ className="h-3.5 w-3.5" />,
          },
          {
            value: "created",
            label: t("display.created"),
            icon: <Clock className="h-3.5 w-3.5" />,
          },
        ]}
        order={order}
        onOrderChange={(v) => onOrder(v as OrderKey)}
        view={view}
        onViewChange={(v) => onView(v as ViewKey)}
      />

      {/* ---------------- applied filter row ---------------- */}
      {filtersOpen && (
        <CollectionFilterRow>
          <FilterSelect
            value={scope || "all"}
            placeholder={t("filters.scope")}
            active={Boolean(scope)}
            onValueChange={onScope}
          >
            <SelectItem value="all">{t("filters.allScopes")}</SelectItem>
            {SCOPE_ORDER.map((s) => (
              <SelectItem key={s} value={s}>
                {tv(SCOPE_META[s].labelKey)}
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
          <CollectionSearchInput
            value={search}
            onChange={onSearch}
            placeholder={t("searchPlaceholder")}
          />
          {hasActiveFilters && (
            <CollectionFilterClear
              onClick={clearFilters}
              label={t("filters.clear")}
            />
          )}
        </CollectionFilterRow>
      )}

      {/* ---------------- body ---------------- */}
      <div className="min-h-0 flex-1 overflow-auto">
        <CollectionView
          view={view}
          containerQuery={false}
          gridClassName="p-4"
          groups={
            view === "list" && group !== "none" ? collectionGroups : undefined
          }
          items={
            view === "grid" || group === "none"
              ? sortItems(visible).map(toItem)
              : undefined
          }
          isLoading={isLoading}
          error={error ? t("error.loadSkills") : undefined}
          emptyState={
            skills.length === 0 ? (
              <div className="p-4">
                <EmptyState
                  title={t("noSkills")}
                  description={t("noSkillsDescription")}
                  iconsType="skills"
                  action={{
                    label: t("addSkill"),
                    onClick: () => router.push("/skills/create"),
                  }}
                />
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center gap-1.5 py-24 text-muted-foreground">
                <Inbox className="h-6 w-6" />
                <p className="text-sm font-semibold text-foreground">
                  {t("emptyHere")}
                </p>
                <p className="text-xs">{t("emptyHereDescription")}</p>
              </div>
            )
          }
        />
      </div>
    </div>
  );
}

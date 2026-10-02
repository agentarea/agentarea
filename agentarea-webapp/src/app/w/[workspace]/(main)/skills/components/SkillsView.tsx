"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { ArrowDownAZ, Clock, Layers, Rows3, Tag } from "lucide-react";
import CatalogSuggestions from "@/components/CatalogSuggestions";
import ContentBlock from "@/components/ContentBlock";
import DisplayMenu from "@/components/DisplayMenu";
import EmptyState from "@/components/EmptyState";
import HeaderTabs from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { GroupHeader } from "@/components/ui/group-header";
import {
  MenuRow,
  MenuSectionLabel,
  MenuSeparator,
} from "@/components/ui/menu-row";
import { listSkillsAction } from "@/lib/server-actions";
import type { PaginatedSkills, Skill } from "@/types/skill";
import { setCookie } from "@/utils/cookies";
import { getValidTimestamp } from "@/utils/dateUtils";
import CreateSkillButton from "./CreateSkillButton";
import SkillRow from "./SkillRow";
import SkillsCard from "./SkillsCard";
import SkillsContentSkeleton from "./SkillsContentSkeleton";
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
  scope: string; // "" | private | ingress | egress
}

// URL params the page keeps in sync, with the value that leaves them out.
const URL_DEFAULTS = {
  view: "list",
  group: "source",
  order: "name",
  network_scope: "",
  search: "",
};
type UrlKey = keyof typeof URL_DEFAULTS;

async function fetchAllSkills(): Promise<Skill[]> {
  const all: Skill[] = [];
  let page = 1;
  // Linear-style grouping needs the full set; page through with a hard cap.
  for (; page <= 20; page++) {
    const { data } = await listSkillsAction({
      page,
      page_size: 100,
      paginated: true,
      // Only your own skills here, installed ones included — the catalog
      // lives in Explore.
      include_catalog: false,
    });
    const res = data as PaginatedSkills | null;
    if (!res?.items?.length) break;
    all.push(...res.items);
    if (!res.has_next) break;
  }
  return all;
}

export default function SkillsView({ initial }: { initial: InitialState }) {
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();
  const t = useTranslations("SkillsPage");

  const [skills, setSkills] = useState<Skill[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  // view/grouping state (URL-shareable)
  const [view, setView] = useState<ViewKey>(initial.view);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [scope, setScope] = useState(initial.scope);
  // The SearchInput in the subheader owns `?search=`; the list reads it back.
  const search = searchParams.get("search") ?? "";

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
    (next: Partial<Record<UrlKey, string>>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(next) as [UrlKey, string][]) {
        if (value && value !== URL_DEFAULTS[key]) params.set(key, value);
        else params.delete(key);
      }
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [searchParams, router, pathname]
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

  const visible = useMemo(() => {
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

  // Counts describe the whole list, independent of the search.
  const scopeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: skills.length };
    for (const s of skills) {
      counts[s.network_scope] = (counts[s.network_scope] ?? 0) + 1;
    }
    return counts;
  }, [skills]);

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
    syncUrl({ network_scope: v });
  };
  const clearFilters = () => {
    setScope("");
    syncUrl({ network_scope: "", search: "" });
  };

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateSkillButton />,
      }}
      subheader={
        <SubheaderToolbar
          categories={
            <CountSegmentedControl
              items={[
                { value: "all", label: t("filters.all") },
                ...SCOPE_ORDER.map((key) => {
                  const Icon = SCOPE_META[key].icon;
                  return {
                    value: key,
                    label: (
                      <span className="flex items-center gap-1.5 whitespace-nowrap">
                        <Icon className="h-4 w-4" strokeWidth={1.8} />
                        {t(`filters.scopeValues.${key}`)}
                      </span>
                    ),
                  };
                }),
              ].map((item) => ({
                ...item,
                count: isLoading ? undefined : (scopeCounts[item.value] ?? 0),
              }))}
              value={scope || "all"}
              onChange={onScope}
              layoutId="skills-scope-filter"
            />
          }
          search={
            <SearchInput
              urlParamName="search"
              delay={250}
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={
            <>
              <DisplayMenu>
                <MenuSectionLabel>{t("display.grouping")}</MenuSectionLabel>
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
                <MenuSeparator />
                <MenuSectionLabel>{t("display.ordering")}</MenuSectionLabel>
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
              </DisplayMenu>
              <HeaderTabs
                value={view}
                onChange={(v) => onView(v as ViewKey)}
                tabs={[
                  { value: "list", label: "List view" },
                  { value: "grid", label: "Grid view" },
                ]}
              />
            </>
          }
        />
      }
      className="p-0"
    >
      {/* The size container lets the rows drop columns as the panel narrows. */}
      <div className="skills-cq">
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
              hints={[
                { text: t("noSkillsHintWrite"), href: "/skills/create" },
                { text: t("noSkillsHintImport"), href: "/skills/create" },
                { text: t("noSkillsHintInstall"), href: "/explore?type=skills" },
              ]}
              iconsType="skills"
              action={{
                label: t("addSkill"),
                onClick: () => router.push("/skills/create"),
              }}
            />
            <CatalogSuggestions type="skills" />
          </div>
        ) : visible.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={t("emptyHere")}
              description={t("emptyHereDescription")}
              iconsType="skills"
              action={{ label: t("filters.clear"), onClick: clearFilters }}
            />
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
    </ContentBlock>
  );
}

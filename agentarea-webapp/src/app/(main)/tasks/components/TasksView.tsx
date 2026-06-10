"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ActivitySquare,
  ArrowDownAZ,
  Bot,
  Clock,
  Coins,
  Inbox,
  Rows3,
} from "lucide-react";
import CollectionView, {
  CollectionFilterClear,
  CollectionFilterRow,
  CollectionSearchInput,
  CollectionToolbar,
  FilterSelect,
  type CollectionGroup,
  type CollectionItem,
} from "@/components/CollectionView";
import { SelectItem } from "@/components/ui/select";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { TaskWithAgent } from "@/lib/api";
import { setCookie } from "@/utils/cookies";
import {
  AgentCell,
  AGENT_COLOR,
  CostCell,
  CreatedCell,
  CreatedInline,
  StatusCell,
  STATUS_GROUP_ORDER,
  statusMeta,
} from "./tasksMeta";

type GroupKey = "status" | "agent" | "none";
type OrderKey = "recent" | "cost" | "name";
type ViewKey = "list" | "grid";

export interface TasksInitialState {
  view: ViewKey;
  group: GroupKey;
  order: OrderKey;
  tab: string; // "all" | "active" | "attention" | "done"
  agent: string; // "" | an agent name
  search: string;
}

function agentName(task: TaskWithAgent): string {
  return task.agent_name || "Unknown agent";
}

function costOf(task: TaskWithAgent): number | null {
  const c = (task as { total_cost?: number | null }).total_cost;
  return c != null && !Number.isNaN(Number(c)) ? Number(c) : null;
}

export default function TasksView({
  tasks,
  initial,
}: {
  tasks: TaskWithAgent[];
  initial: TasksInitialState;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const t = useTranslations("TasksPage");
  const tv = useTranslations("TasksPage.view");

  const [view, setView] = useState<ViewKey>(initial.view);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [tab, setTab] = useState(initial.tab);
  const [agent, setAgent] = useState(initial.agent);
  const [search, setSearch] = useState(initial.search);
  const [filtersOpen, setFiltersOpen] = useState(Boolean(initial.agent));

  const syncUrl = useCallback(
    (next: Partial<TasksInitialState>) => {
      const merged = { view, group, order, tab, agent, search, ...next };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "list");
      set("group", merged.group, "none");
      set("order", merged.order, "recent");
      set("tab", merged.tab, "all");
      set("agent", merged.agent, "");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [view, group, order, tab, agent, search, searchParams, router, pathname]
  );

  // agent + search filters drive the tab counts
  const baseFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tasks.filter((task) => {
      if (agent && agentName(task) !== agent) return false;
      if (q) {
        const hay =
          `${task.description ?? ""} ${agentName(task)} ${task.status ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [tasks, agent, search]);

  const inTab = useCallback((task: TaskWithAgent, key: string) => {
    const s = statusMeta(task.status).key;
    if (key === "active") return s === "run" || s === "pending";
    if (key === "attention") return s === "input" || s === "fail";
    if (key === "done") return s === "done";
    return true;
  }, []);

  const tabs = useMemo(() => {
    const count = (key: string) =>
      baseFiltered.filter((task) => inTab(task, key)).length;
    return [
      { value: "all", label: t("tabsBar.all"), count: baseFiltered.length },
      { value: "active", label: t("tabsBar.active"), count: count("active") },
      {
        value: "attention",
        label: t("tabsBar.attention"),
        count: count("attention"),
      },
      { value: "done", label: t("tabsBar.done"), count: count("done") },
    ];
  }, [baseFiltered, inTab, t]);

  const agentOptions = useMemo(() => {
    const set = new Set<string>();
    for (const task of tasks) set.add(agentName(task));
    return [...set].sort((a, b) => a.localeCompare(b));
  }, [tasks]);

  const visible = useMemo(
    () => baseFiltered.filter((task) => inTab(task, tab)),
    [baseFiltered, tab, inTab]
  );

  const sortTasks = useCallback(
    (arr: TaskWithAgent[]) => {
      const a = [...arr];
      if (order === "cost") {
        a.sort((x, y) => (costOf(y) ?? 0) - (costOf(x) ?? 0));
      } else if (order === "name") {
        a.sort((x, y) => (x.description || "").localeCompare(y.description || ""));
      } else {
        a.sort(
          (x, y) =>
            new Date(y.created_at).getTime() - new Date(x.created_at).getTime()
        );
      }
      return a;
    },
    [order]
  );

  const toItem = useCallback((task: TaskWithAgent): CollectionItem => {
    const name = agentName(task);
    const cost = costOf(task);
    return {
      id: task.id,
      icon: Bot,
      color: AGENT_COLOR,
      title: task.description,
      href: `/tasks/${task.id}`,
      hideIcon: true,
      hideDescription: true,
      // metaPlain: bypass the row's collapse-at-620 wrapper so each column drops
      // on its own breakpoint. Status is the exception — it never hides (just
      // collapses to its dot when narrow), like the name.
      metaPlain: true,
      meta: (
        <div className="flex items-center gap-3.5 text-left">
          <AgentCell
            name={name}
            className="collection-col-source w-[150px] min-w-[150px]"
          />
          <StatusCell status={task.status} className="collection-status" />
          <CostCell
            cost={cost}
            className="collection-col-scope w-[84px] text-right"
          />
          <CreatedCell
            iso={task.created_at}
            className="collection-col-date w-[112px]"
          />
        </div>
      ),
      headerAside: (
        <StatusCell status={task.status} dotOnly className="-translate-y-[1px]" />
      ),
      cardFooter: (
        <div className="flex min-w-0 items-center gap-2 pr-6 text-[11.5px] text-muted-foreground">
          <AgentCell name={name} size={16} className="min-w-0 shrink" />
          <span className="text-border">·</span>
          <CostCell cost={cost} />
          <span className="text-border">·</span>
          <CreatedInline iso={task.created_at} />
        </div>
      ),
    };
  }, []);

  const collectionGroups = useMemo<CollectionGroup[]>(() => {
    if (group === "none") return [];
    const sorted = sortTasks(visible);

    if (group === "status") {
      const buckets = new Map<string, TaskWithAgent[]>();
      for (const task of sorted) {
        const key = statusMeta(task.status).key;
        const list = buckets.get(key) ?? [];
        list.push(task);
        buckets.set(key, list);
      }
      return STATUS_GROUP_ORDER.filter((k) => buckets.has(k)).map((k) => {
        const sm = statusMeta(k);
        return {
          key: sm.key,
          label: tv(sm.labelKey),
          color: sm.color,
          items: (buckets.get(k) ?? []).map(toItem),
        };
      });
    }

    // group === "agent"
    const buckets = new Map<string, TaskWithAgent[]>();
    for (const task of sorted) {
      const name = agentName(task);
      const list = buckets.get(name) ?? [];
      list.push(task);
      buckets.set(name, list);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([name, list]) => ({
        key: name,
        label: name,
        color: AGENT_COLOR,
        items: list.map(toItem),
      }));
  }, [group, visible, sortTasks, toItem, tv]);

  const hasActiveFilters = Boolean(agent) || Boolean(search) || tab !== "all";

  const onView = (value: ViewKey) => {
    setView(value);
    setCookie("view_tasks", value);
    syncUrl({ view: value });
  };
  const onAgent = (value: string) => {
    const v = value === "all" ? "" : value;
    setAgent(v);
    syncUrl({ agent: v });
  };
  const onSearch = (value: string) => {
    setSearch(value);
    syncUrl({ search: value });
  };
  const clearFilters = () => {
    setAgent("");
    setSearch("");
    setTab("all");
    syncUrl({ agent: "", search: "", tab: "all" });
  };

  const iconCls = "h-3.5 w-3.5";

  return (
    <TooltipProvider delayDuration={150}>
      <div className="collection-cq flex h-full w-full flex-col">
        <CollectionToolbar
          tabs={tabs}
          activeTab={tab}
          onTabChange={(v) => {
            setTab(v);
            syncUrl({ tab: v });
          }}
          filterLabel={t("filters.filter")}
          filterActive={filtersOpen}
          onToggleFilter={() => setFiltersOpen((v) => !v)}
          displayLabel={t("display.display")}
          groupingLabel={t("display.grouping")}
          groupOptions={[
            {
              value: "none",
              label: t("display.none"),
              icon: <Rows3 className={iconCls} />,
            },
            {
              value: "status",
              label: t("display.status"),
              icon: <ActivitySquare className={iconCls} />,
            },
            {
              value: "agent",
              label: t("display.agent"),
              icon: <Bot className={iconCls} />,
            },
          ]}
          group={group}
          onGroupChange={(v) => {
            setGroup(v as GroupKey);
            syncUrl({ group: v as GroupKey });
          }}
          orderingLabel={t("display.ordering")}
          orderOptions={[
            {
              value: "recent",
              label: t("display.recent"),
              icon: <Clock className={iconCls} />,
            },
            {
              value: "cost",
              label: t("display.cost"),
              icon: <Coins className={iconCls} />,
            },
            {
              value: "name",
              label: t("display.name"),
              icon: <ArrowDownAZ className={iconCls} />,
            },
          ]}
          order={order}
          onOrderChange={(v) => {
            setOrder(v as OrderKey);
            syncUrl({ order: v as OrderKey });
          }}
          view={view}
          onViewChange={onView}
          listLabel={t("display.listView")}
          gridLabel={t("display.gridView")}
        />

        {filtersOpen && (
          <CollectionFilterRow>
            <FilterSelect
              value={agent || "all"}
              placeholder={t("filters.agent")}
              active={Boolean(agent)}
              onValueChange={onAgent}
            >
              <SelectItem value="all">{t("filters.allAgents")}</SelectItem>
              {agentOptions.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
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

        <div className="min-h-0 flex-1 overflow-auto">
          <CollectionView
            view={view}
            containerQuery={false}
            gridClassName="p-4"
            gridMinWidth={232}
            groups={
              view === "list" && group !== "none" ? collectionGroups : undefined
            }
            items={
              view === "grid" || group === "none"
                ? sortTasks(visible).map(toItem)
                : undefined
            }
            emptyState={
              <div className="flex flex-col items-center justify-center gap-1.5 py-24 text-muted-foreground">
                <Inbox className="h-6 w-6" />
                <p className="text-sm font-semibold text-foreground">
                  {t("emptyHere")}
                </p>
                <p className="text-xs">{t("emptyHereDescription")}</p>
              </div>
            }
          />
        </div>
      </div>
    </TooltipProvider>
  );
}

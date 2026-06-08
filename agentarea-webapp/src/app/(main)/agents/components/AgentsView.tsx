"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Activity, ArrowDownAZ, Bot, Brain, Inbox, Rows3, X } from "lucide-react";
import CollectionView, {
  CollectionFilterRow,
  CollectionToolbar,
  FilterSelect,
  type CollectionGroup,
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { SelectItem } from "@/components/ui/select";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Agent, ModelInfo } from "@/types/agent";
import { setCookie } from "@/utils/cookies";
import {
  ModelCell,
  modelLabel,
  StatusCell,
  statusMeta,
  STATUS_GROUP_ORDER,
  TasksCell,
  ToolsCell,
} from "./agentMeta";

export type EnrichedAgent = Agent & {
  model_info?: ModelInfo | null;
  active_task_count?: number;
};

type GroupKey = "status" | "model" | "none";
type OrderKey = "name" | "tasks";
type ViewKey = "list" | "grid";

export interface AgentsInitialState {
  view: ViewKey;
  group: GroupKey;
  order: OrderKey;
  statusTab: string; // "all" | a resolved status label
  model: string; // "" | a model label
  search: string;
}

const AGENT_COLOR = "#5e6ad2";

export default function AgentsView({
  agents,
  initial,
}: {
  agents: EnrichedAgent[];
  initial: AgentsInitialState;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const t = useTranslations("AgentsPage");

  const [view, setView] = useState<ViewKey>(initial.view);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [statusTab, setStatusTab] = useState(initial.statusTab);
  const [model, setModel] = useState(initial.model);
  const [search, setSearch] = useState(initial.search);
  const [filtersOpen, setFiltersOpen] = useState(Boolean(initial.model));

  // Sync the shareable bits of state into the URL without a navigation.
  const syncUrl = useCallback(
    (next: Partial<AgentsInitialState>) => {
      const merged = { view, group, order, statusTab, model, search, ...next };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "list");
      set("group", merged.group, "status");
      set("order", merged.order, "name");
      set("status", merged.statusTab, "all");
      set("model", merged.model, "");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [view, group, order, statusTab, model, search, searchParams, router, pathname]
  );

  const modelKey = (a: EnrichedAgent) => modelLabel(a.model_info) || "No model";

  // model / search filters — also drive the status tab counts
  const baseFiltered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return agents.filter((a) => {
      if (model && modelKey(a) !== model) return false;
      if (q) {
        const hay =
          `${a.name} ${a.description ?? ""} ${modelLabel(a.model_info)} ${a.model_info?.provider_name ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [agents, model, search]);

  // status tabs (only statuses that exist, ordered)
  const statusTabs = useMemo(() => {
    const counts = new Map<string, number>();
    for (const a of baseFiltered) {
      const label = statusMeta(a.status).label;
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    const labelOrder = (label: string) => {
      const idx = STATUS_GROUP_ORDER.findIndex(
        (s) => statusMeta(s).label === label
      );
      return idx < 0 ? 99 : idx;
    };
    const tabs = [...counts.entries()]
      .sort(([a], [b]) => labelOrder(a) - labelOrder(b) || a.localeCompare(b))
      .map(([label, n]) => ({ value: label, label, count: n }));
    return [
      { value: "all", label: t("filters.all"), count: baseFiltered.length },
      ...tabs,
    ];
  }, [baseFiltered, t]);

  const modelOptions = useMemo(() => {
    const set = new Set<string>();
    for (const a of agents) set.add(modelKey(a));
    return [...set].sort((a, b) =>
      a === "No model" ? 1 : b === "No model" ? -1 : a.localeCompare(b)
    );
  }, [agents]);

  const visible = useMemo(
    () =>
      statusTab === "all"
        ? baseFiltered
        : baseFiltered.filter((a) => statusMeta(a.status).label === statusTab),
    [baseFiltered, statusTab]
  );

  const sortAgents = useCallback(
    (arr: EnrichedAgent[]) => {
      const a = [...arr];
      if (order === "tasks") {
        a.sort(
          (x, y) =>
            (y.active_task_count ?? 0) - (x.active_task_count ?? 0) ||
            x.name.localeCompare(y.name)
        );
      } else {
        a.sort((x, y) => x.name.localeCompare(y.name));
      }
      return a;
    },
    [order]
  );

  const toItem = useCallback((agent: EnrichedAgent): CollectionItem => {
    const m = agent.model_info;
    const activeCount = agent.active_task_count ?? 0;
    return {
      id: agent.id,
      icon: Bot,
      color: AGENT_COLOR,
      title: agent.name,
      description: agent.description,
      href: `/agents/${agent.id}`,
      meta: (
        <div className="flex items-center gap-3.5 text-left">
          <ModelCell model={m} className="w-[188px] min-w-[188px]" />
          <StatusCell
            status={agent.status}
            className="collection-col-source w-[78px]"
          />
          <TasksCell
            count={activeCount}
            className="collection-col-scope w-[60px]"
          />
          <ToolsCell agent={agent} className="collection-col-date w-[104px]" />
        </div>
      ),
      headerAside: (
        <StatusCell
          status={agent.status}
          dotOnly
          className="-translate-y-[1.5px]"
        />
      ),
      hideDescription: true,
      cardFooter: (
        <>
          <ModelCell model={m} className="mb-2" />
          <div className="flex items-center gap-3">
            <TasksCell count={activeCount} />
            <ToolsCell agent={agent} />
          </div>
        </>
      ),
    };
  }, []);

  const collectionGroups = useMemo<CollectionGroup[]>(() => {
    if (group === "none") return [];
    const sorted = sortAgents(visible);

    if (group === "status") {
      const buckets = new Map<
        string,
        { label: string; color: string; order: number; items: EnrichedAgent[] }
      >();
      for (const agent of sorted) {
        const sm = statusMeta(agent.status);
        const ord = STATUS_GROUP_ORDER.indexOf(
          (agent.status || "").toLowerCase()
        );
        const bucket = buckets.get(sm.label) ?? {
          label: sm.label,
          color: sm.color,
          order: ord < 0 ? 99 : ord,
          items: [],
        };
        bucket.items.push(agent);
        buckets.set(sm.label, bucket);
      }
      return [...buckets.values()]
        .sort((a, b) => a.order - b.order || a.label.localeCompare(b.label))
        .map((b) => ({
          key: b.label,
          label: b.label,
          color: b.color,
          items: b.items.map(toItem),
        }));
    }

    // group === "model"
    const buckets = new Map<string, EnrichedAgent[]>();
    for (const agent of sorted) {
      const label = modelKey(agent);
      const list = buckets.get(label) ?? [];
      list.push(agent);
      buckets.set(label, list);
    }
    return [...buckets.entries()]
      .sort(([a], [b]) =>
        a === "No model" ? 1 : b === "No model" ? -1 : a.localeCompare(b)
      )
      .map(([label, list]) => ({
        key: label,
        label,
        color: label === "No model" ? "#a4a8b0" : AGENT_COLOR,
        items: list.map(toItem),
      }));
  }, [group, visible, sortAgents, toItem]);

  const hasActiveFilters =
    Boolean(model) || Boolean(search) || statusTab !== "all";

  // ---- toolbar handlers ----
  const onView = (value: ViewKey) => {
    setView(value);
    setCookie("view_agents", value);
    syncUrl({ view: value });
  };
  const onModel = (value: string) => {
    const v = value === "all" ? "" : value;
    setModel(v);
    syncUrl({ model: v });
  };
  const onSearch = (value: string) => {
    setSearch(value);
    syncUrl({ search: value });
  };
  const clearFilters = () => {
    setModel("");
    setSearch("");
    setStatusTab("all");
    syncUrl({ model: "", search: "", statusTab: "all" });
  };

  const iconCls = "h-3.5 w-3.5";

  return (
    <TooltipProvider delayDuration={150}>
      <div className="collection-cq flex h-full w-full flex-col">
        <CollectionToolbar
          tabs={statusTabs}
          activeTab={statusTab}
          onTabChange={(v) => {
            setStatusTab(v);
            syncUrl({ statusTab: v });
          }}
          filterLabel={t("filters.filter")}
          filterActive={filtersOpen}
          onToggleFilter={() => setFiltersOpen((v) => !v)}
          displayLabel={t("display.display")}
          groupingLabel={t("display.grouping")}
          groupOptions={[
            {
              value: "status",
              label: t("display.status"),
              icon: <Activity className={iconCls} />,
            },
            {
              value: "model",
              label: t("display.model"),
              icon: <Brain className={iconCls} />,
            },
            {
              value: "none",
              label: t("display.none"),
              icon: <Rows3 className={iconCls} />,
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
              value: "name",
              label: t("display.name"),
              icon: <ArrowDownAZ className={iconCls} />,
            },
            {
              value: "tasks",
              label: t("display.activeTasks"),
              icon: <Activity className={iconCls} />,
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
              value={model || "all"}
              placeholder={t("filters.model")}
              active={Boolean(model)}
              onValueChange={onModel}
            >
              <SelectItem value="all">{t("filters.allModels")}</SelectItem>
              {modelOptions.map((m) => (
                <SelectItem key={m} value={m}>
                  {m}
                </SelectItem>
              ))}
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
          </CollectionFilterRow>
        )}

        <div className="min-h-0 flex-1 overflow-auto">
          <CollectionView
            view={view}
            containerQuery={false}
            gridClassName="p-4"
            gridMinWidth={230}
            groups={
              view === "list" && group !== "none" ? collectionGroups : undefined
            }
            items={
              view === "grid" || group === "none"
                ? sortAgents(visible).map(toItem)
                : undefined
            }
            emptyState={
              agents.length === 0 ? (
                <EmptyState
                  title={t("noAgentsTitle")}
                  description={t("noAgentsDescription")}
                  iconsType="agent"
                  action={{
                    label: t("deployNewAgent"),
                    onClick: () => router.push("/agents/create"),
                  }}
                />
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
    </TooltipProvider>
  );
}

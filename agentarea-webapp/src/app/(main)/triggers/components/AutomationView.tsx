"use client";

import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Activity,
  ArrowDownAZ,
  Bot,
  Clock,
  Rows3,
  Tag,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import CollectionView, {
  AgentChip,
  CollectionFilterClear,
  CollectionFilterRow,
  CollectionSearchInput,
  CollectionToolbar,
  StatusDot,
  type CollectionGroup,
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import { setCookie } from "@/utils/cookies";
import { findTriggerCatalogEntry } from "./triggerDisplay";

type ViewKey = "list" | "grid";
type TabKey = "all" | "cron" | "webhook";
type GroupKey = "none" | "status" | "type" | "agent";
type OrderKey = "name" | "status" | "next";

export interface AutomationInitialState {
  view: ViewKey;
  tab: TabKey;
  group: GroupKey;
  order: OrderKey;
  search: string;
}

interface AutomationViewProps {
  triggers: any[];
  catalog: any[];
  initial: AutomationInitialState;
}

/* ── type (cron / webhook) ─────────────────────────────────────────────── */

/** A next-intl translator (loosely typed for use in module-level helpers). */
type TFn = (key: string, values?: Record<string, string | number>) => string;

type TypeKey = "cron" | "webhook";
const TYPE_META: Record<TypeKey, { icon: LucideIcon; color: string }> = {
  cron: { icon: Clock, color: "#2252b3" },
  webhook: { icon: Webhook, color: "#7a5af5" },
};

function triggerKind(trigger: any): TypeKey {
  return trigger.trigger_type === "cron" ? "cron" : "webhook";
}

/* ── status (active / paused / error) ──────────────────────────────────── */

type StatusKey = "active" | "paused" | "error";
const STATUS_META: Record<StatusKey, { labelKey: string; color: string }> = {
  active: { labelKey: "statusActive", color: "#1f9d6b" },
  paused: { labelKey: "statusPaused", color: "#8a8f98" },
  error: { labelKey: "statusError", color: "#d6453d" },
};
const STATUS_ORDER: StatusKey[] = ["error", "active", "paused"];

function triggerStatus(trigger: any): StatusKey {
  if (!trigger.is_active) return "paused";
  if ((trigger.consecutive_failures ?? 0) > 0) return "error";
  return "active";
}

/* ── schedule + next-run text ──────────────────────────────────────────── */

/** Format `hour minute` (24h fields) as e.g. "9:00", or the localized
 *  "midnight" / "noon". */
function clockText(hourField: string, minField: string, tv: TFn): string | null {
  const h = Number(hourField);
  const m = Number(minField);
  if (!Number.isInteger(h) || !Number.isInteger(m)) return null;
  if (h === 0 && m === 0) return tv("midnight");
  if (h === 12 && m === 0) return tv("noon");
  return `${h}:${String(m).padStart(2, "0")}`;
}

/** Turn a standard 5-field cron expression into localized English/Russian,
 *  falling back to the raw expression for anything exotic. */
function humanizeCron(expr: string, tv: TFn): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length < 5) return expr;
  const [min, hour, dom, mon, dow] = parts;
  const everyDay = dom === "*" && mon === "*" && dow === "*";

  // Every N minutes / every minute / every hour
  if (hour === "*" && everyDay) {
    if (min === "*") return tv("everyMinute");
    if (/^\*\/\d+$/.test(min)) return tv("everyNMinutes", { n: Number(min.slice(2)) });
    if (min === "0") return tv("everyHour");
  }
  // Every N hours
  if (min === "0" && /^\*\/\d+$/.test(hour) && everyDay) {
    return tv("everyNHours", { n: Number(hour.slice(2)) });
  }

  const time = clockText(hour, min, tv);
  if (time) {
    if (everyDay) return tv("everyDayAt", { time });
    if (dom === "*" && mon === "*") {
      if (dow === "1-5") return tv("weekdaysAt", { time });
      if (dow === "0,6" || dow === "6,0") return tv("weekendsAt", { time });
      const d = Number(dow);
      if (Number.isInteger(d) && d >= 0 && d <= 6) {
        return tv("everyWeekdayAt", { day: d, time });
      }
    }
    if (/^\d+$/.test(dom) && dow === "*") {
      return tv("monthlyAt", { dom, time });
    }
  }
  return expr;
}

function scheduleText(trigger: any, entry: any, kind: TypeKey, tv: TFn): string {
  if (kind === "cron") {
    if (trigger.cron_expression) return humanizeCron(trigger.cron_expression, tv);
    return trigger.description || tv("scheduled");
  }
  const sub = entry?.name || trigger.webhook_type;
  if (sub && !/^(generic|webhook)$/i.test(sub)) return tv("onSub", { name: sub });
  return trigger.description || tv("onIncomingRequest");
}

/** Compact future delta, e.g. "in 3m", "in 9h", "in 5d". */
function relativeFuture(iso: string | null | undefined, tv: TFn): string | null {
  if (!iso) return null;
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return null;
  const diff = ts - Date.now();
  if (diff <= 0) return tv("relNow");
  const m = Math.round(diff / 60_000);
  if (m < 60) return tv("relMin", { n: m });
  const h = Math.round(m / 60);
  if (h < 24) return tv("relHour", { n: h });
  return tv("relDay", { n: Math.round(h / 24) });
}

/* ── small presentational pieces (match the prototype) ─────────────────── */

function TypePill({ kind }: { kind: TypeKey }) {
  const t = useTranslations("TriggersPage");
  const { icon: Icon, color } = TYPE_META[kind];
  return (
    <span className="inline-flex h-[22px] w-max items-center gap-1.5 rounded-md border border-border bg-background px-2 text-[11.5px] font-medium text-foreground/80">
      <Icon className="h-3.5 w-3.5" strokeWidth={1.8} style={{ color }} />
      {t(`type.${kind}`)}
    </span>
  );
}


function NextRun({ iso }: { iso?: string | null }) {
  const tv = useTranslations("TriggersPage.view");
  const rel = relativeFuture(iso, tv);
  if (!rel) {
    return <span className="text-[12px] text-muted-foreground/60">—</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] tabular-nums text-foreground/70">
      <Clock className="h-3 w-3" strokeWidth={1.7} />
      {rel}
    </span>
  );
}

function StatusChip({ status }: { status: StatusKey }) {
  const tv = useTranslations("TriggersPage.view");
  const s = STATUS_META[status];
  return (
    <StatusDot color={s.color} label={tv(s.labelKey)} className="text-[12px]" />
  );
}

/* ── view ──────────────────────────────────────────────────────────────── */

export default function AutomationView({
  triggers,
  catalog,
  initial,
}: AutomationViewProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const tc = useTranslations("Collection");
  const t = useTranslations("TriggersPage");
  const tv = useTranslations("TriggersPage.view");

  const [view, setView] = useState<ViewKey>(initial.view);
  const [tab, setTab] = useState<TabKey>(initial.tab);
  const [group, setGroup] = useState<GroupKey>(initial.group);
  const [order, setOrder] = useState<OrderKey>(initial.order);
  const [search, setSearch] = useState(initial.search);
  const [filtersOpen, setFiltersOpen] = useState(Boolean(initial.search));

  // ── URL sync ──
  const syncUrl = useCallback(
    (next: Partial<AutomationInitialState>) => {
      const merged = { view, tab, group, order, search, ...next };
      const params = new URLSearchParams(searchParams.toString());
      const set = (key: string, value: string, empty: string) => {
        if (value && value !== empty) params.set(key, value);
        else params.delete(key);
      };
      set("view", merged.view, "grid");
      set("type", merged.tab, "all");
      set("group", merged.group, "none");
      set("order", merged.order, "name");
      set("search", merged.search, "");
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [view, tab, group, order, search, searchParams, router, pathname]
  );

  // ── trigger entries ──
  type Entry = {
    item: CollectionItem;
    kind: TypeKey;
    status: StatusKey;
    agent: string;
    name: string;
    next: string | null;
    text: string;
  };

  const entries = useMemo<Entry[]>(
    () =>
      triggers.map((trigger): Entry => {
        const kind = triggerKind(trigger);
        const entry = findTriggerCatalogEntry(trigger, catalog);
        const status = triggerStatus(trigger);
        const agent = trigger.agent_name || "Unknown agent";
        const schedule = scheduleText(trigger, entry, kind, tv);
        const { color, icon: Icon } = TYPE_META[kind];
        return {
          kind,
          status,
          agent,
          name: trigger.name,
          next: trigger.next_run_time ?? null,
          text: `${trigger.name} ${agent} ${schedule}`.toLowerCase(),
          item: {
            id: trigger.id,
            color,
            icon: Icon,
            title: trigger.name,
            titleClassName: "w-[200px] shrink-0",
            description: schedule,
            href: `/triggers/${trigger.id}`,
            meta: (
              <span
                className="grid items-center gap-3 text-left"
                style={{ gridTemplateColumns: "88px 160px 86px 96px" }}
              >
                <TypePill kind={kind} />
                <AgentChip name={agent} tooltip={false} />
                <NextRun iso={trigger.next_run_time} />
                <StatusChip status={status} />
              </span>
            ),
            // grid card: schedule as the muted subline, pills + agent below
            cardSubtitle: schedule,
            hideDescription: true,
            cardFooter: (
              <div className="flex flex-col gap-2.5">
                <div className="flex items-center gap-2">
                  <TypePill kind={kind} />
                  <StatusChip status={status} />
                </div>
                <AgentChip name={agent} tooltip={false} className="pr-6" />
              </div>
            ),
          },
        };
      }),
    [triggers, catalog, tv]
  );

  // ── filtering ──
  const q = search.trim().toLowerCase();
  const visible = useMemo(
    () =>
      entries.filter((e) => {
        if (tab !== "all" && e.kind !== tab) return false;
        return !q || e.text.includes(q);
      }),
    [entries, tab, q]
  );

  const sortEntries = useCallback(
    (arr: Entry[]) => {
      const out = [...arr];
      if (order === "status") {
        out.sort(
          (a, b) =>
            STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
            a.name.localeCompare(b.name)
        );
      } else if (order === "next") {
        const v = (e: Entry) =>
          e.next ? new Date(e.next).getTime() : Number.POSITIVE_INFINITY;
        out.sort((a, b) => v(a) - v(b) || a.name.localeCompare(b.name));
      } else {
        out.sort((a, b) => a.name.localeCompare(b.name));
      }
      return out;
    },
    [order]
  );

  // ── grouped (list view) vs flat ──
  const groups = useMemo<CollectionGroup[] | undefined>(() => {
    if (view !== "list" || group === "none") return undefined;
    if (group === "status") {
      return STATUS_ORDER.map((key) => ({
        key,
        label: tv(STATUS_META[key].labelKey),
        color: STATUS_META[key].color,
        items: sortEntries(visible.filter((e) => e.status === key)).map(
          (e) => e.item
        ),
      })).filter((g) => g.items.length > 0);
    }
    if (group === "type") {
      return (["cron", "webhook"] as TypeKey[])
        .map((key) => ({
          key,
          label: t(`type.${key}`),
          color: TYPE_META[key].color,
          items: sortEntries(visible.filter((e) => e.kind === key)).map(
            (e) => e.item
          ),
        }))
        .filter((g) => g.items.length > 0);
    }
    // by agent
    const agents = [...new Set(visible.map((e) => e.agent))].sort((a, b) =>
      a.localeCompare(b)
    );
    return agents
      .map((agent) => ({
        key: agent,
        label: agent,
        color: "#a4a8b0",
        items: sortEntries(visible.filter((e) => e.agent === agent)).map(
          (e) => e.item
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [view, group, visible, sortEntries, t, tv]);

  const items = useMemo(
    () => sortEntries(visible).map((e) => e.item),
    [visible, sortEntries]
  );

  // ── tab counts ──
  const counts = useMemo(() => {
    const cron = entries.filter((e) => e.kind === "cron").length;
    return { all: entries.length, cron, webhook: entries.length - cron };
  }, [entries]);

  // ── handlers ──
  const onTab = (v: string) => {
    setTab(v as TabKey);
    syncUrl({ tab: v as TabKey });
  };
  const onView = (v: ViewKey) => {
    setView(v);
    setCookie("view_triggers", v);
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

  return (
    <div className="collection-cq flex h-full w-full flex-col">
      <CollectionToolbar
        tabs={[
          { value: "all", label: tc("all"), count: counts.all },
          { value: "cron", label: t("type.cron"), count: counts.cron },
          { value: "webhook", label: t("type.webhook"), count: counts.webhook },
        ]}
        activeTab={tab}
        onTabChange={onTab}
        filterActive={filtersOpen}
        onToggleFilter={() => setFiltersOpen((v) => !v)}
        groupOptions={[
          { value: "none", label: tc("noGrouping"), icon: <Rows3 className="h-3.5 w-3.5" /> },
          { value: "status", label: tc("status"), icon: <Activity className="h-3.5 w-3.5" /> },
          { value: "type", label: tc("type"), icon: <Tag className="h-3.5 w-3.5" /> },
          { value: "agent", label: tc("agent"), icon: <Bot className="h-3.5 w-3.5" /> },
        ]}
        group={group}
        onGroupChange={onGroup}
        orderOptions={[
          { value: "name", label: tc("name"), icon: <ArrowDownAZ className="h-3.5 w-3.5" /> },
          { value: "status", label: tc("status"), icon: <Activity className="h-3.5 w-3.5" /> },
          { value: "next", label: tc("nextRun"), icon: <Clock className="h-3.5 w-3.5" /> },
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
        {entries.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={t("noTriggers")}
              description={t("noTriggersDescription")}
              iconsType="triggers"
            />
          </div>
        ) : (
          <CollectionView
            view={view}
            containerQuery={false}
            gridClassName="px-4 pb-5 pt-3.5"
            gridMinWidth={196}
            groups={groups}
            items={groups ? undefined : items}
            emptyState={
              <div className="px-4 py-3 text-[12px] text-muted-foreground">
                {search
                  ? tv("noMatch")
                  : tv("noneInView")}
              </div>
            }
          />
        )}
      </div>
    </div>
  );
}

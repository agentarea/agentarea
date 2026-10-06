"use client";

import { createElement, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { endOfDay, isBefore, startOfDay } from "date-fns";
import {
  Boxes,
  CalendarRange,
  CheckCheck,
  ChevronDown,
  Clock,
  ListFilter,
  Users,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import ToolbarSelect from "@/components/ToolbarSelect";
import { MenuRow } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { RangeCalendar } from "@/components/ui/range-calendar";
import { ToolbarButton } from "@/components/ui/toolbar";
import {
  useWorkspacePathname,
  useWorkspaceRouter,
} from "@/hooks/useWorkspaceNavigation";
import type { AuditActorOption } from "./actions";
import {
  actionsFor,
  actionSubject,
  AUDIT_FILTER_PARAMS,
  AUDIT_PERIODS,
  AUDIT_RESOURCE_TYPES,
  isFiltered,
  parseAuditFilters,
  type AuditFilters,
  type AuditPeriod,
} from "./auditFilters";
import { auditActorIcon, auditResourceIcon, auditVerbIcon } from "./auditIcons";
import { auditVerb, auditVerbTone } from "./format";

const ALL = "all";
const ICON = "h-3.5 w-3.5 text-muted-foreground";
const icon = (glyph: LucideIcon) =>
  createElement(glyph, { className: ICON, "aria-hidden": true });

/** The filters in the URL, and a way to change some of them. */
function useAuditFilters() {
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const searchParams = useSearchParams();

  const update = (patch: Partial<Record<keyof AuditFilters, string>>) => {
    const params = new URLSearchParams(searchParams.toString());
    for (const name of AUDIT_FILTER_PARAMS) {
      if (!(name in patch)) continue;
      const value = patch[name];
      if (value) params.set(name, value);
      else params.delete(name);
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };

  return { filters: parseAuditFilters(searchParams), update };
}

/** The audit log subheader's filters, right to left as they narrow less. */
export default function AuditLogToolbar({
  actorFilter,
}: {
  /** The actor filter; its options load on the server. */
  actorFilter: React.ReactNode;
}) {
  return (
    <>
      <ResetFilters />
      <ResourceFilter />
      <ActionFilter />
      {actorFilter}
      <PeriodFilter />
    </>
  );
}

function ResetFilters() {
  const t = useTranslations("AuditLogPage.filters");
  const { filters, update } = useAuditFilters();
  if (!isFiltered(filters)) return null;

  return (
    <ToolbarButton
      aria-label={t("reset")}
      onClick={() =>
        update(
          Object.fromEntries(AUDIT_FILTER_PARAMS.map((name) => [name, ""]))
        )
      }
    >
      <X className={ICON} />
      <span className="max-sm:sr-only">{t("reset")}</span>
    </ToolbarButton>
  );
}

function ResourceFilter() {
  const t = useTranslations("AuditLogPage");
  const { filters, update } = useAuditFilters();

  return (
    <ToolbarSelect
      label={t("filters.resourceType")}
      value={filters.resource ?? ALL}
      onChange={(value) => {
        const resource = value === ALL ? "" : value;
        // An action about another kind of thing would match nothing.
        const stale =
          filters.action && !actionsFor(resource).includes(filters.action);
        update(stale ? { resource, action: "" } : { resource });
      }}
      groups={[
        [{ value: ALL, label: t("filters.allResources"), icon: icon(Boxes) }],
        AUDIT_RESOURCE_TYPES.map((type) => ({
          value: type,
          label: t(`resourceTypes.${type}`),
          icon: icon(auditResourceIcon(type) ?? Boxes),
        })),
      ]}
    />
  );
}

/** The glyph of what an action is about, heading its group in the menu. */
function subjectIcon(subject: string): LucideIcon {
  if (subject === "tool.call") return Wrench;
  if (subject === "approval") return CheckCheck;
  if (subject === "access") return auditResourceIcon("access_grant") ?? Boxes;
  return auditResourceIcon(subject) ?? Boxes;
}

function ActionFilter() {
  const t = useTranslations("AuditLogPage");
  const { filters, update } = useAuditFilters();

  // The subject an action is about, as the people reading the log name it.
  const subjectLabel = (subject: string) =>
    subject === "tool.call"
      ? t("actionSubjects.toolCall")
      : subject === "approval"
        ? t("actionSubjects.approval")
        : subject === "access"
          ? t("resourceTypes.access_grant")
          : t.has(`resourceTypes.${subject}`)
            ? t(`resourceTypes.${subject}`)
            : subject;

  const verbLabel = (action: string) => {
    const verb = auditVerb(action);
    return t.has(`verbs.${verb}`) ? t(`verbs.${verb}`) : verb;
  };

  // One group per subject, in the order the trail lists them; a picked
  // resource leaves only its own.
  const sections = new Map<string, string[]>();
  for (const action of actionsFor(filters.resource)) {
    const subject = actionSubject(action);
    sections.set(subject, [...(sections.get(subject) ?? []), action]);
  }

  return (
    <ToolbarSelect
      collapsible
      label={t("filters.action")}
      value={filters.action ?? ALL}
      onChange={(value) => update({ action: value === ALL ? "" : value })}
      groups={[
        [
          {
            value: ALL,
            label: t("filters.allActions"),
            icon: icon(ListFilter),
          },
        ],
        ...[...sections].map(([subject, actions]) => ({
          label: subjectLabel(subject),
          icon: icon(subjectIcon(subject)),
          options: actions.map((action) => ({
            value: action,
            label: verbLabel(action),
            triggerLabel: `${subjectLabel(subject)} · ${verbLabel(action)}`,
            icon: createElement(
              auditVerbIcon(auditVerb(action)) ?? ListFilter,
              {
                className: "h-3.5 w-3.5",
                style: { color: auditVerbTone(action) },
                "aria-hidden": true,
              }
            ),
          })),
        })),
      ]}
    />
  );
}

/** People and agents who can appear as the actor of an event. */
export function ActorFilter({ options }: { options: AuditActorOption[] }) {
  const t = useTranslations("AuditLogPage.filters");
  const { filters, update } = useAuditFilters();
  const option = (kind: AuditActorOption["kind"]) =>
    options
      .filter((item) => item.kind === kind)
      .map((item) => ({
        value: item.value,
        label: item.label,
        icon: icon(auditActorIcon(kind)),
      }));

  return (
    <ToolbarSelect
      label={t("actor")}
      value={filters.actor ?? ALL}
      onChange={(value) => update({ actor: value === ALL ? "" : value })}
      groups={[
        [{ value: ALL, label: t("anyone"), icon: icon(Users) }],
        option("user"),
        option("agent"),
      ]}
    />
  );
}

function PeriodFilter() {
  const t = useTranslations("AuditLogPage.filters");
  const format = useFormatter();
  const { filters, update } = useAuditFilters();
  const [open, setOpen] = useState(false);
  // The first day of a custom range while the second is still to be picked.
  const [rangeStart, setRangeStart] = useState<Date | null>(null);
  const { period, since, until } = filters;
  const short = (instant: string | Date) =>
    format.dateTime(new Date(instant), { day: "numeric", month: "short" });

  const label = period
    ? t(`periods.${period}`)
    : since && until
      ? t("range", { from: short(since), to: short(until) })
      : since
        ? t("fromDate", { date: short(since) })
        : until
          ? t("untilDate", { date: short(until) })
          : t("anyTime");

  // The days the filter covers now, or the range being picked.
  const shownRange = () => {
    if (rangeStart) return { from: rangeStart };
    if (period) {
      return {
        from: new Date(Date.now() - AUDIT_PERIODS[period]),
        to: new Date(),
      };
    }
    return {
      from: since ? new Date(since) : undefined,
      to: until ? new Date(until) : undefined,
    };
  };

  const toggle = (next: boolean) => {
    setOpen(next);
    setRangeStart(null);
  };

  const choose = (next?: AuditPeriod) => {
    toggle(false);
    update({ period: next ?? "", since: "", until: "" });
  };

  // Two clicks make a range, in either order; the same day twice is that day.
  const pick = (day: Date) => {
    if (!rangeStart) {
      setRangeStart(day);
      return;
    }
    const [first, last] = isBefore(day, rangeStart)
      ? [day, rangeStart]
      : [rangeStart, day];
    toggle(false);
    update({
      period: "",
      since: startOfDay(first).toISOString(),
      until: endOfDay(last).toISOString(),
    });
  };

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <ToolbarButton active={open} aria-label={t("period")}>
          <CalendarRange className={ICON} />
          <span className="max-sm:sr-only">{label}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70" />
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-auto max-w-[calc(100vw-1rem)] p-0"
        aria-label={t("period")}
      >
        <div className="flex flex-col sm:flex-row">
          <div className="p-1.5 max-sm:border-b sm:w-44 sm:border-r sm:border-border/60">
            <MenuRow
              icon={icon(CalendarRange)}
              label={t("anyTime")}
              selected={!period && !since && !until}
              onClick={() => choose()}
            />
            {(Object.keys(AUDIT_PERIODS) as AuditPeriod[]).map((value) => (
              <MenuRow
                key={value}
                icon={icon(Clock)}
                label={t(`periods.${value}`)}
                selected={period === value}
                onClick={() => choose(value)}
              />
            ))}
          </div>
          <div className="p-3">
            <RangeCalendar
              {...shownRange()}
              onPick={pick}
              max={endOfDay(new Date())}
            />
            <p className="mt-2 text-center text-xs text-muted-foreground">
              {rangeStart
                ? t("pickEnd", { date: short(rangeStart) })
                : t("pickStart")}
            </p>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

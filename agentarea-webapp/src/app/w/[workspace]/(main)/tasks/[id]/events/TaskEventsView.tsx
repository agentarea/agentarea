"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown, ChevronRight } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import SearchInput from "@/components/SearchInput";
import { TableSkeleton } from "@/components/Skeleton";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import Table, { type Column } from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import ToolbarRefreshButton from "@/components/ToolbarRefreshButton";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import type { DisplayEvent, EventLevel } from "@/types/events";
import {
  EventDescriptionCell,
  EventTypeCell,
  useEventLabel,
} from "./TaskEventCells";
import {
  countEventLevels,
  EVENT_LEVEL_FILTERS,
  filterTaskEvents,
  type EventLevelFilter,
} from "./taskEventsFilter";

const LEVEL_KINDS: Record<
  EventLevel,
  "active" | "attention" | "done" | "failed"
> = {
  info: "active",
  success: "done",
  warning: "attention",
  error: "failed",
};

/** `index` is the event's place in the whole run, kept while filtering. */
type EventRow = DisplayEvent & { index: number };

function hasData(event: DisplayEvent) {
  return Boolean(event.data && Object.keys(event.data).length > 0);
}

interface TaskEventsViewProps {
  /** The whole run, oldest first. */
  events: DisplayEvent[];
  /** Nothing to show yet: the task or its history is still loading. */
  loading: boolean;
  /** A reload is in flight, with or without events on screen. */
  refreshing: boolean;
  error: string | null;
  /** The live stream is connected. */
  connected: boolean;
  onRefresh: () => void;
}

/** A task's events: filtered by level and text, each row opening its data. */
export default function TaskEventsView({
  events,
  loading,
  refreshing,
  error: eventsError,
  connected,
  onRefresh: refresh,
}: TaskEventsViewProps) {
  const t = useTranslations("TaskEventsPage");
  const tCommon = useTranslations("Common");
  const labelOf = useEventLabel();
  const [search, setSearch] = useState("");
  // Bumped to clear the search box, which keeps its own text.
  const [searchKey, setSearchKey] = useState(0);
  const [level, setLevel] = useState<EventLevelFilter>("all");
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());

  // The search finds an event by the name it reads as, too.
  const counts = useMemo(
    () => countEventLevels(events, search, labelOf),
    [events, search, labelOf]
  );
  const rows = useMemo<EventRow[]>(() => {
    const positions = new Map(events.map((event, i) => [event.id, i + 1]));
    return filterTaskEvents(events, { level, search, labelOf }).map(
      (event) => ({
        ...event,
        index: positions.get(event.id) ?? 0,
      })
    );
  }, [events, level, search, labelOf]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const clearFilters = () => {
    setLevel("all");
    setSearch("");
    setSearchKey((key) => key + 1);
  };

  const columns: Column<EventRow>[] = [
    {
      accessor: "expand",
      header: "",
      cellClassName: "w-6 pr-0",
      render: (_, event) => {
        if (!event || !hasData(event)) return null;
        const open = expanded.has(event.id);
        const Chevron = open ? ChevronDown : ChevronRight;
        return (
          <button
            type="button"
            aria-expanded={open}
            aria-label={t(open ? "hideData" : "showData")}
            onClick={(e) => {
              // The row toggles too; one click must not toggle twice.
              e.stopPropagation();
              toggle(event.id);
            }}
            className="-m-1 grid h-6 w-6 place-items-center rounded text-muted-foreground/70 hover:bg-muted hover:text-foreground"
          >
            <Chevron className="h-3.5 w-3.5" />
          </button>
        );
      },
    },
    {
      accessor: "index",
      header: t("columns.index"),
      headerClassName: "w-10",
      cellClassName: "w-10 text-xs tabular-nums text-muted-foreground",
    },
    {
      accessor: "timestamp",
      header: t("columns.time"),
      headerClassName: "w-[130px]",
      cellClassName: "w-[130px] tabular-nums",
      // Events of one task are moments apart: the time down to milliseconds.
      render: (value) =>
        value instanceof Date ? (
          <TableDateDisplay dateString={value.toISOString()} precise />
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      accessor: "type",
      header: t("columns.type"),
      headerClassName: "w-[230px]",
      cellClassName: "w-[230px] max-w-[230px]",
      render: (value) => <EventTypeCell type={String(value)} />,
    },
    {
      accessor: "level",
      header: t("columns.level"),
      headerClassName: "w-[150px]",
      cellClassName: "w-[150px]",
      render: (value) => {
        const eventLevel = value as EventLevel;
        return (
          <StatusIndicator kind={LEVEL_KINDS[eventLevel]} size="sm">
            {t(`levels.${eventLevel}`)}
          </StatusIndicator>
        );
      },
    },
    {
      accessor: "description",
      header: t("columns.description"),
      cellClassName: "min-w-0",
      render: (_, event) =>
        event && (
          <EventDescriptionCell event={event}>
            {expanded.has(event.id) && hasData(event) && (
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 font-mono text-[11px] text-muted-foreground">
                {JSON.stringify(event.data, null, 2)}
              </pre>
            )}
          </EventDescriptionCell>
        ),
    },
  ];

  let body: React.ReactNode;
  if (loading) {
    body = (
      <TableSkeleton
        rows={10}
        columns={[
          { header: "", barClassName: "h-4 w-4" },
          { header: t("columns.index"), barClassName: "h-4 w-5" },
          { header: t("columns.time"), barClassName: "h-4 w-20" },
          { header: t("columns.type"), barClassName: "h-4 w-32" },
          { header: t("columns.level"), barClassName: "h-4 w-16" },
          { header: t("columns.description"), barClassName: "h-4 w-64" },
        ]}
      />
    );
  } else if (eventsError && events.length === 0) {
    body = (
      <EmptyState
        title={t("loadFailed")}
        description={eventsError}
        iconsType="tasks"
        action={{ label: tCommon("retry"), onClick: refresh }}
      />
    );
  } else if (events.length === 0) {
    body = (
      <EmptyState
        title={t("empty")}
        description={t("emptyDescription")}
        iconsType="tasks"
      />
    );
  } else if (rows.length === 0) {
    body = (
      <EmptyState
        title={t("noMatches")}
        description={t("noMatchesDescription")}
        iconsType="tasks"
        action={{ label: t("clearFilters"), onClick: clearFilters }}
      />
    );
  } else {
    body = (
      <>
        {/* Events already shown stay up; only the failure is new. */}
        {eventsError && <FormError className="mb-3">{eventsError}</FormError>}
        <Table<EventRow>
          data={rows}
          columns={columns}
          onRowClick={(event) => hasData(event) && toggle(event.id)}
          rowProps={(event) => ({
            className: cn(
              // An open row's data runs long: its cells stay on the first line.
              expanded.has(event.id) && "[&>td]:align-top",
              !hasData(event) &&
                "cursor-default hover:bg-transparent dark:hover:bg-transparent"
            ),
          })}
        />
      </>
    );
  }

  return (
    <ContentBlock
      subheader={
        <SubheaderToolbar
          categories={
            <div role="group" aria-label={t("levelFilter")} className="min-w-0">
              <CountSegmentedControl<EventLevelFilter>
                items={EVENT_LEVEL_FILTERS.map((value) => ({
                  value,
                  label: t(`levels.${value}`),
                  count: counts[value],
                }))}
                value={level}
                onChange={setLevel}
                variant="subtle"
                className="max-w-full"
                layoutId="task-event-level"
              />
            </div>
          }
          search={
            <SearchInput
              key={searchKey}
              onDebouncedChange={setSearch}
              delay={200}
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={
            <>
              <StatusIndicator kind={connected ? "active" : "failed"} size="sm">
                {connected ? t("live") : t("offline")}
              </StatusIndicator>
              <ToolbarRefreshButton
                onRefresh={refresh}
                refreshing={refreshing}
              />
            </>
          }
        />
      }
    >
      {body}
    </ContentBlock>
  );
}

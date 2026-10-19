"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUp, ChevronRight, Paperclip } from "lucide-react";
import type { FeedEventResponse, Processing } from "@/api/client/types.gen";
import SourceTypeMark from "@/components/SourceTypeMark";
import Table, { type Column } from "@/components/Table/Table";
import { Button } from "@/components/ui/button";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  applyProcessing,
  applyRecorded,
  dayGroups,
  feedHref,
  matchesResult,
  type FeedState,
} from "@/lib/eventFeed";
import {
  feedItems,
  feedStops,
  groupsPlatformRuns,
  isRunExpanded,
  neighbourStop,
  PLATFORM_SOURCE_TYPE,
  runHolding,
  type FeedStop,
  type PlatformRun,
} from "@/lib/eventFeedRuns";
import { isPlatformStream } from "@/lib/platformStream";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { cn } from "@/lib/utils";
import { useFeedLive } from "./FeedLive";
import { useFeedSelection } from "./FeedSelection";
import ProcessingPill, { ProcessingRunPill } from "./ProcessingPill";

/** `Table` keys rows by `id`; a run of platform events is one row. */
type FeedRow =
  | { id: string; type: "event"; event: FeedEventResponse; child: boolean }
  | { id: string; type: "run"; run: PlatformRun; expanded: boolean };

const rowDomId = (stop: FeedStop) => `feed-row-${stop.id}`;

/** Scrolled further than this, a new event waits behind the "N new" pill. */
const AT_TOP_PX = 48;

function scrollParent(node: HTMLElement | null): HTMLElement | null {
  let current = node?.parentElement ?? null;
  while (current) {
    const overflow = getComputedStyle(current).overflowY;
    if (overflow === "auto" || overflow === "scroll") return current;
    current = current.parentElement;
  }
  return null;
}

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

/**
 * The workspace feed's rows: the page the server read, and what arrived since
 * on top, one table per day. Clicking a row opens it in the side panel
 * (`?event=`); up and down move through the list.
 */
export default function FeedList({
  initial,
  nextBefore,
  state,
  streams,
  sourceTypes,
}: {
  initial: FeedEventResponse[];
  nextBefore: number | null;
  state: FeedState;
  streams: { id: string; name: string; kind: string }[];
  sourceTypes: SourceType[];
}) {
  const t = useTranslations("EventsPage.list");
  const tFeed = useTranslations("EventsPage.feed");
  const locale = useLocale();
  const router = useWorkspaceRouter();
  const { listen } = useFeedLive();
  const { pending, select } = useFeedSelection();
  const selected = pending === undefined ? state.event : pending;
  const listRef = useRef<HTMLDivElement>(null);
  const [arrived, setArrived] = useState<FeedEventResponse[]>([]);
  const [held, setHeld] = useState<FeedEventResponse[]>([]);
  const [moved, setMoved] = useState<Record<string, Processing>>({});
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const [cursorRun, setCursorRun] = useState<string | null>(null);
  const [entered, setEntered] = useState<string | null | undefined>(undefined);
  // The viewer's clock and zone, known once mounted; the server renders UTC.
  const [clock, setClock] = useState<{ now: number; zone: string } | null>(
    null
  );
  const live = state.before === undefined;

  useEffect(() => {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    setClock({ now: Date.now(), zone });
    const timer = setInterval(() => setClock({ now: Date.now(), zone }), 1000);
    return () => clearInterval(timer);
  }, []);

  const selectedRef = useRef(state.event);
  selectedRef.current = state.event;

  useEffect(() => {
    if (!live) return;
    let refresh: ReturnType<typeof setTimeout> | undefined;
    const stop = listen((message) => {
      if (message.type === "resync") {
        router.refresh();
        return;
      }
      if (message.type === "recorded") {
        const parent = scrollParent(listRef.current);
        if (parent && parent.scrollTop > AT_TOP_PX) {
          setHeld((rows) => applyRecorded(rows, message.event));
        } else {
          setArrived((rows) => applyRecorded(rows, message.event));
        }
        return;
      }
      setMoved((all) => ({ ...all, [message.eventId]: message.processing }));
      if (message.eventId === selectedRef.current) {
        clearTimeout(refresh);
        refresh = setTimeout(() => router.refresh(), 300);
      }
    });
    return () => {
      stop();
      clearTimeout(refresh);
    };
  }, [listen, live, router]);

  const rows = useMemo(() => {
    let merged = initial;
    for (const event of arrived) merged = applyRecorded(merged, event);
    for (const [id, processing] of Object.entries(moved)) {
      merged = applyProcessing(merged, id, processing);
    }
    return merged.filter((e) => matchesResult(e, state.result));
  }, [initial, arrived, moved, state.result]);

  const waiting = held.filter(
    (e) =>
      matchesResult(e, state.result) &&
      !rows.some((r) => r.event_id === e.event_id)
  );

  const showHeld = () => {
    setArrived((rows) => held.reduce(applyRecorded, rows));
    setHeld([]);
    scrollParent(listRef.current)?.scrollTo({ top: 0, behavior: "smooth" });
  };

  useEffect(() => {
    const parent = scrollParent(listRef.current);
    if (!parent || held.length === 0) return;
    const onScroll = () => {
      if (parent.scrollTop <= AT_TOP_PX) {
        setArrived((rows) => held.reduce(applyRecorded, rows));
        setHeld([]);
      }
    };
    parent.addEventListener("scroll", onScroll, { passive: true });
    return () => parent.removeEventListener("scroll", onScroll);
  }, [held]);

  const streamNames = new Map(streams.map((s) => [s.id, s.name]));
  const zone = clock?.zone ?? "UTC";
  const group = groupsPlatformRuns(
    state,
    streams.filter(isPlatformStream).map((s) => s.id)
  );
  const days = dayGroups(rows, new Date(clock?.now ?? Date.now()), zone).map(
    (day) => ({ ...day, items: feedItems(day.events, group) })
  );
  const items = days.flatMap((day) => day.items);
  if (entered !== selected) {
    setEntered(selected);
    const holding = runHolding(items, selected);
    if (holding && !opened.has(holding.id)) {
      setOpened((ids) => new Set(ids).add(holding.id));
    }
  }
  const expanded = (run: PlatformRun) => isRunExpanded(run, opened, selected);
  const stops = feedStops(items, expanded);
  const filtered = Boolean(
    state.stream ||
      state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );

  const open = (eventId: string) => {
    setCursorRun(null);
    select(feedHref(state, { event: eventId }), eventId);
  };

  const moveTo = (stop: FeedStop) => {
    if (stop.type === "event") open(stop.id);
    else setCursorRun(stop.id);
    const row = document.getElementById(rowDomId(stop));
    row?.focus({ preventScroll: true });
    row?.scrollIntoView({ block: "nearest" });
  };

  const toggle = (run: PlatformRun) => {
    setCursorRun(run.id);
    if (!expanded(run)) {
      setOpened((ids) => new Set(ids).add(run.id));
      return;
    }
    setOpened((ids) => {
      const next = new Set(ids);
      next.delete(run.id);
      return next;
    });
    if (run.events.some((e) => e.event_id === selected)) {
      select(feedHref(state, { event: undefined }), null);
    }
  };

  const keys = useRef({ stops, items, cursorRun, selected, moveTo });
  keys.current = { stops, items, cursorRun, selected, moveTo };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || isTyping(e.target)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const { stops, items, cursorRun, selected, moveTo } = keys.current;
      if (e.key === "ArrowLeft") {
        const run = cursorRun ? undefined : runHolding(items, selected);
        if (!run) return;
        e.preventDefault();
        moveTo({ type: "run", id: run.id });
        return;
      }
      const step =
        e.key === "ArrowDown" || e.key === "j"
          ? 1
          : e.key === "ArrowUp" || e.key === "k"
            ? -1
            : 0;
      if (step === 0) return;
      const current: FeedStop | undefined = cursorRun
        ? { type: "run", id: cursorRun }
        : selected
          ? { type: "event", id: selected }
          : undefined;
      const next = neighbourStop(stops, current, step);
      if (!next) return;
      e.preventDefault();
      moveTo(next);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const onRunKey = (run: PlatformRun, e: React.KeyboardEvent) => {
    const isOpen = expanded(run);
    if (e.key === "Enter" || e.key === " ") toggle(run);
    else if (e.key === "ArrowRight" && !isOpen) toggle(run);
    else if (e.key === "ArrowRight")
      moveTo({ type: "event", id: run.events[0].event_id });
    else if (e.key === "ArrowLeft" && isOpen) toggle(run);
    else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const timeOf = (iso: string) =>
    new Date(iso).toLocaleTimeString(locale, {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: zone,
    });
  const dateTimeOf = (iso: string) =>
    new Date(iso).toLocaleString(locale, {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: zone,
    });

  const columns: Column<FeedRow>[] = [
    {
      header: tFeed("received"),
      accessor: "received_at",
      cellClassName: "w-0 whitespace-nowrap tabular-nums text-muted-foreground",
      render: (_value, row) => {
        if (!row) return null;
        if (row.type === "event") {
          return (
            <time
              dateTime={row.event.received_at}
              title={dateTimeOf(row.event.received_at)}
            >
              {timeOf(row.event.received_at)}
            </time>
          );
        }
        return (
          <span
            title={`${dateTimeOf(row.run.oldest)} – ${dateTimeOf(row.run.newest)}`}
          >
            <span className="sm:hidden">{timeOf(row.run.newest)}</span>
            <span className="hidden sm:inline">
              {new Intl.DateTimeFormat(locale, {
                hour: "2-digit",
                minute: "2-digit",
                timeZone: zone,
              }).formatRange(
                new Date(row.run.oldest),
                new Date(row.run.newest)
              )}
            </span>
          </span>
        );
      },
    },
    {
      header: tFeed("kind"),
      accessor: "kind",
      cellClassName: "w-full max-w-0",
      render: (_value, row) => {
        if (!row) return null;
        if (row.type === "run") {
          const breakdown = row.run.kinds
            .map(({ kind, count }) => `${kind} ${count}`)
            .join(" · ");
          return (
            <span className="flex min-w-0 items-center gap-2">
              <SourceTypeMark
                type={sourceTypeBySlug(sourceTypes, PLATFORM_SOURCE_TYPE)}
                slug={PLATFORM_SOURCE_TYPE}
                inline
                className="h-3.5 w-3.5 shrink-0"
              />
              <span className="truncate font-medium">
                {t("platformRun", { count: row.run.events.length })}
              </span>
              <ChevronRight
                aria-hidden="true"
                className={cn(
                  "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
                  row.expanded && "rotate-90"
                )}
              />
              <span
                title={breakdown}
                className="hidden shrink-[100] truncate tabular-nums text-muted-foreground sm:block"
              >
                {breakdown}
              </span>
            </span>
          );
        }
        const { event } = row;
        return (
          <span
            className={cn(
              "flex min-w-0 items-center gap-2",
              row.child && "pl-3 sm:pl-[22px]"
            )}
          >
            <SourceTypeMark
              type={sourceTypeBySlug(sourceTypes, event.source_type)}
              slug={event.source_type}
              inline
              className="h-3.5 w-3.5 shrink-0"
            />
            <span className="truncate font-medium">{event.kind}</span>
            {event.sender && (
              <span className="truncate text-muted-foreground">
                {event.sender}
              </span>
            )}
            {event.attachments > 0 && (
              <Paperclip
                aria-hidden="true"
                className="h-3 w-3 shrink-0 text-muted-foreground"
              />
            )}
          </span>
        );
      },
    },
    {
      header: t("stream"),
      accessor: "stream_id",
      headerClassName: "hidden md:table-cell",
      cellClassName:
        "hidden max-w-[160px] truncate text-muted-foreground md:table-cell",
      render: (_value, row) => {
        if (!row) return null;
        const streamId =
          row.type === "event"
            ? row.event.stream_id
            : row.run.events[0].stream_id;
        return streamNames.get(streamId) ?? t("unknownStream");
      },
    },
    {
      header: t("session"),
      accessor: "session_key",
      headerClassName: "hidden 2xl:table-cell",
      cellClassName: "hidden max-w-[160px] truncate 2xl:table-cell",
      render: (_value, row) =>
        row?.type === "event" &&
        row.event.session_key && (
          <WorkspaceLink
            href={feedHref(state, {
              session: row.event.session_key,
              event: undefined,
              before: undefined,
            })}
            scroll={false}
            title={t("filterSession")}
            onClick={(e) => e.stopPropagation()}
            className="font-mono text-muted-foreground hover:text-primary hover:underline"
          >
            {row.event.session_key.split(":").slice(1).join(":") ||
              row.event.session_key}
          </WorkspaceLink>
        ),
    },
    {
      header: t("result"),
      accessor: "processing",
      cellClassName: "w-0 whitespace-nowrap",
      render: (_value, row) => {
        if (!row) return null;
        if (row.type === "run") return <ProcessingRunPill run={row.run} />;
        return (
          <ProcessingPill
            processing={row.event.processing}
            receivedAt={row.event.received_at}
            now={clock?.now ?? null}
          />
        );
      },
    },
  ];

  const tableRows = (day: (typeof days)[number]): FeedRow[] =>
    day.items.flatMap((item): FeedRow[] => {
      if (item.type === "event") {
        const { event } = item;
        return [{ id: event.event_id, type: "event", event, child: false }];
      }
      const { run } = item;
      const open = expanded(run);
      return [
        { id: run.id, type: "run", run, expanded: open },
        ...(open
          ? run.events.map(
              (event): FeedRow => ({
                id: event.event_id,
                type: "event",
                event,
                child: true,
              })
            )
          : []),
      ];
    });

  const rowProps = (row: FeedRow): React.HTMLAttributes<HTMLElement> => {
    if (row.type === "run") {
      return {
        id: rowDomId(row),
        role: "button",
        tabIndex: 0,
        "aria-expanded": row.expanded,
        onFocus: () => setCursorRun(row.id),
        onKeyDown: (e) => onRunKey(row.run, e),
        className: "outline-none focus-visible:bg-muted/40",
      };
    }
    const { event } = row;
    return {
      id: rowDomId({ type: "event", id: event.event_id }),
      role: "link",
      tabIndex: 0,
      onFocus: () => setCursorRun(null),
      onKeyDown: (e) => {
        if (e.key === "Enter") open(event.event_id);
      },
      ...(event.event_id === selected ? { "aria-current": "true" } : {}),
      className: cn(
        "outline-none focus-visible:bg-muted/40",
        row.child && "bg-muted/20",
        event.event_id === selected && "bg-muted/40"
      ),
    };
  };

  return (
    <div ref={listRef} className="min-w-0 space-y-5">
      {waiting.length > 0 && (
        <div className="sticky top-0 z-10 flex justify-center">
          <Button
            size="xs"
            variant="primaryOutline"
            className="gap-1 rounded-full px-3 shadow"
            onClick={showHeld}
          >
            <ArrowUp />
            {t("newEvents", { count: waiting.length })}
          </Button>
        </div>
      )}
      {rows.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {filtered ? t("noneMatching") : t("empty")}
        </div>
      ) : (
        days.map((day, index) => (
          <section key={day.day} aria-label={day.day}>
            <h2 className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              {day.relative
                ? t(day.relative)
                : new Date(`${day.day}T12:00:00Z`).toLocaleDateString(locale, {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                    timeZone: "UTC",
                  })}
            </h2>
            <Table<FeedRow>
              data={tableRows(day)}
              columns={columns}
              hideHeader={index > 0}
              onRowClick={(row) =>
                row.type === "run" ? toggle(row.run) : open(row.event.event_id)
              }
              rowProps={rowProps}
            />
          </section>
        ))
      )}
      {nextBefore != null && (
        <WorkspaceLink
          href={feedHref(state, {
            before: String(nextBefore),
            event: undefined,
          })}
          className="text-sm text-primary hover:underline"
        >
          {t("older")}
        </WorkspaceLink>
      )}
    </div>
  );
}

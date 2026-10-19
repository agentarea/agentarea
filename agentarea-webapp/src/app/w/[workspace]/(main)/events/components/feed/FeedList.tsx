"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUp, Paperclip } from "lucide-react";
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
  neighbourEvent,
  type FeedState,
} from "@/lib/eventFeed";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { useFeedLive } from "./FeedLive";
import { useFeedSelection } from "./FeedSelection";
import ProcessingPill from "./ProcessingPill";

/** `Table` keys rows by `id`. */
type FeedRow = FeedEventResponse & { id: string };

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
 * (`?event=`, set in place); up and down move through the list.
 */
export default function FeedList({
  initial,
  nextBefore,
  state,
  streams,
  sourceTypes,
  hidesPlatform,
}: {
  initial: FeedEventResponse[];
  nextBefore: number | null;
  state: FeedState;
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
  /** The platform's own events are left out, and there are some. */
  hidesPlatform: boolean;
}) {
  const t = useTranslations("EventsPage.list");
  const tFeed = useTranslations("EventsPage.feed");
  const locale = useLocale();
  const router = useWorkspaceRouter();
  const { listen } = useFeedLive();
  const { selected, select } = useFeedSelection();
  const listRef = useRef<HTMLDivElement>(null);
  const [arrived, setArrived] = useState<FeedEventResponse[]>([]);
  const [held, setHeld] = useState<FeedEventResponse[]>([]);
  const [moved, setMoved] = useState<Record<string, Processing>>({});
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

  useEffect(() => {
    if (!live) return;
    return listen((message) => {
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
    });
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

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const step =
        e.key === "ArrowDown" || e.key === "j"
          ? 1
          : e.key === "ArrowUp" || e.key === "k"
            ? -1
            : 0;
      if (step === 0) return;
      const next = neighbourEvent(rows, selected ?? undefined, step);
      if (!next) return;
      e.preventDefault();
      select(next, selected != null);
      document
        .getElementById(`feed-row-${next}`)
        ?.scrollIntoView({ block: "nearest" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, selected, select]);

  const open = (eventId: string) => select(eventId);
  const streamNames = new Map(streams.map((s) => [s.id, s.name]));
  const zone = clock?.zone ?? "UTC";
  const groups = dayGroups(rows, new Date(clock?.now ?? Date.now()), zone);
  const filtered = Boolean(
    hidesPlatform ||
      state.stream ||
      state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );

  const columns: Column<FeedRow>[] = [
    {
      header: tFeed("received"),
      accessor: "received_at",
      cellClassName: "w-0 whitespace-nowrap tabular-nums text-muted-foreground",
      render: (_value, event) =>
        event && (
          <time
            dateTime={event.received_at}
            title={new Date(event.received_at).toLocaleString(locale, {
              dateStyle: "medium",
              timeStyle: "medium",
              timeZone: zone,
            })}
          >
            {new Date(event.received_at).toLocaleTimeString(locale, {
              hour: "2-digit",
              minute: "2-digit",
              timeZone: zone,
            })}
          </time>
        ),
    },
    {
      header: tFeed("kind"),
      accessor: "kind",
      cellClassName: "w-full max-w-0",
      render: (_value, event) =>
        event && (
          <span className="flex min-w-0 items-center gap-2">
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
        ),
    },
    {
      header: t("stream"),
      accessor: "stream_id",
      headerClassName: "hidden md:table-cell",
      cellClassName:
        "hidden max-w-[160px] truncate text-muted-foreground md:table-cell",
      render: (value) => streamNames.get(String(value)) ?? t("unknownStream"),
    },
    {
      header: t("session"),
      accessor: "session_key",
      headerClassName: "hidden 2xl:table-cell",
      cellClassName: "hidden max-w-[160px] truncate 2xl:table-cell",
      render: (_value, event) =>
        event?.session_key && (
          <WorkspaceLink
            href={feedHref(state, {
              session: event.session_key,
              event: undefined,
              before: undefined,
            })}
            scroll={false}
            title={t("filterSession")}
            onClick={(e) => e.stopPropagation()}
            className="font-mono text-muted-foreground hover:text-primary hover:underline"
          >
            {event.session_key.split(":").slice(1).join(":") ||
              event.session_key}
          </WorkspaceLink>
        ),
    },
    {
      header: t("result"),
      accessor: "processing",
      cellClassName: "w-0 whitespace-nowrap",
      render: (_value, event) =>
        event && (
          <ProcessingPill
            processing={event.processing}
            receivedAt={event.received_at}
            now={clock?.now ?? null}
          />
        ),
    },
  ];

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
        groups.map((group, index) => (
          <section key={group.day} aria-label={group.day}>
            <h2 className="mb-2 text-[11px] uppercase tracking-wide text-muted-foreground">
              {group.relative
                ? t(group.relative)
                : new Date(`${group.day}T12:00:00Z`).toLocaleDateString(
                    locale,
                    {
                      day: "numeric",
                      month: "long",
                      year: "numeric",
                      timeZone: "UTC",
                    }
                  )}
            </h2>
            <Table<FeedRow>
              data={group.events.map((event) => ({
                ...event,
                id: event.event_id,
              }))}
              columns={columns}
              hideHeader={index > 0}
              onRowClick={(event) => open(event.event_id)}
              rowProps={(event) => ({
                id: `feed-row-${event.event_id}`,
                role: "link",
                tabIndex: 0,
                onKeyDown: (e) => {
                  if (e.key === "Enter") open(event.event_id);
                },
                ...(event.event_id === selected
                  ? { "aria-current": "true", className: "bg-muted/40" }
                  : {}),
              })}
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

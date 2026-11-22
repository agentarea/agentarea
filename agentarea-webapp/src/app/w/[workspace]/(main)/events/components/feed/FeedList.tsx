"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUp, MessagesSquare } from "lucide-react";
import type { FeedEventResponse, Processing } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import { useViewerZone } from "@/components/EventTime";
import { Button } from "@/components/ui/button";
import WorkspaceLink from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  applyProcessing,
  applyRecorded,
  dayGroups,
  feedHref,
  foldRuns,
  matchesResult,
  neighbourEvent,
  showsPlatform,
  type FeedState,
} from "@/lib/eventFeed";
import type { SourceType } from "@/lib/sourceTypes";
import { readOlderEventsAction } from "./actions";
import { useFeedLive } from "./FeedLive";
import FeedRow, { type FeedAgent } from "./FeedRow";
import { useFeedSelection } from "./FeedSelection";

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
  platformStreams,
  sourceTypes,
  agents,
  hidesPlatform,
}: {
  initial: FeedEventResponse[];
  nextBefore: number | null;
  state: FeedState;
  streams: { id: string; name: string }[];
  platformStreams: string[];
  sourceTypes: SourceType[];
  agents: FeedAgent[];
  /** The platform's own events are left out, and there are some. */
  hidesPlatform: boolean;
}) {
  const t = useTranslations("EventsPage.list");
  const locale = useLocale();
  const router = useWorkspaceRouter();
  const { listen } = useFeedLive();
  const { selected, select } = useFeedSelection();
  const listRef = useRef<HTMLDivElement>(null);
  const [arrived, setArrived] = useState<FeedEventResponse[]>([]);
  const [held, setHeld] = useState<FeedEventResponse[]>([]);
  const [moved, setMoved] = useState<Record<string, Processing>>({});
  const [older, setOlder] = useState<FeedEventResponse[]>([]);
  const [cursor, setCursor] = useState(nextBefore);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderFailed, setOlderFailed] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  // The viewer's clock, known once mounted.
  const [now, setNow] = useState<number | null>(null);
  const zone = useViewerZone();
  const live = state.before === undefined;

  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 60_000);
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
    const seen = new Set(initial.map((e) => e.event_id));
    let merged = [...initial, ...older.filter((e) => !seen.has(e.event_id))];
    for (const event of arrived) merged = applyRecorded(merged, event);
    for (const [id, processing] of Object.entries(moved)) {
      merged = applyProcessing(merged, id, processing);
    }
    return merged.filter((e) => matchesResult(e, state.result));
  }, [initial, older, arrived, moved, state.result]);

  const loadOlder = async () => {
    if (cursor == null || loadingOlder) return;
    setLoadingOlder(true);
    setOlderFailed(false);
    const page = await readOlderEventsAction(
      state,
      showsPlatform(state, platformStreams),
      cursor
    ).catch(() => null);
    setLoadingOlder(false);
    if (!page) {
      setOlderFailed(true);
      return;
    }
    setOlder((rows) => [...rows, ...page.events]);
    setCursor(page.nextBefore);
  };

  useEffect(() => {
    const end = endRef.current;
    if (!end || cursor == null || loadingOlder || olderFailed) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) void loadOlder();
      },
      { root: scrollParent(end), rootMargin: "400px" }
    );
    observer.observe(end);
    return () => observer.disconnect();
  });

  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const groups = useMemo(
    () =>
      dayGroups(rows, new Date(now ?? Date.now()), zone).map((group) => ({
        ...group,
        items: foldRuns(
          group.events,
          selected ? new Set(expanded).add(selected) : expanded
        ),
      })),
    [rows, now, zone, expanded, selected]
  );
  const visible = useMemo(
    () => groups.flatMap((g) => g.items.map((i) => i.event)),
    [groups]
  );

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
      const next = neighbourEvent(visible, selected ?? undefined, step);
      if (!next) return;
      e.preventDefault();
      select(next, selected != null);
      document
        .getElementById(`feed-row-${next}`)
        ?.scrollIntoView({ block: "nearest" });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selected, select]);

  const open = (eventId: string) => select(eventId);
  const streamNames = new Map(streams.map((s) => [s.id, s.name]));
  const agentsById = new Map(agents.map((a) => [a.id, a]));
  const streamName = (id: string) => streamNames.get(id) ?? t("unknownStream");
  const narrowed = Boolean(
    state.stream ||
      state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );

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
        narrowed ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {t("noneMatching")}
          </div>
        ) : hidesPlatform ? (
          <div className="py-6 text-center text-sm text-muted-foreground">
            {t("onlyPlatform")}{" "}
            <WorkspaceLink
              href={feedHref(state, { platform: undefined, event: undefined })}
              scroll={false}
              className="text-primary hover:underline"
            >
              {t("showPlatform")}
            </WorkspaceLink>
          </div>
        ) : (
          <EmptyState
            title={t("empty")}
            description={t("emptyDescription")}
            icons={[MessagesSquare, ENTITY_ICONS.stream, ENTITY_ICONS.trigger]}
            action={{ label: t("emptyChannel"), href: "/channels/new" }}
            additionAction={{
              label: t("emptyStreams"),
              href: "/events/streams",
            }}
          />
        )
      ) : (
        <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-700 [&>div:last-child>div]:border-b-0">
          {groups.map((group) => (
            <section key={group.day} aria-label={group.day}>
              <h2 className="border-b border-zinc-200 bg-muted/40 px-4 py-1 text-[11px] uppercase tracking-wide text-muted-foreground dark:border-zinc-700">
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
              {group.items.map(({ event, folded }) => (
                <div key={event.event_id} id={`feed-row-${event.event_id}`}>
                  <FeedRow
                    event={event}
                    count={folded.length + 1}
                    sourceTypes={sourceTypes}
                    agents={agentsById}
                    streamName={
                      state.stream || platformStreams.includes(event.stream_id)
                        ? null
                        : streamName(event.stream_id)
                    }
                    selected={event.event_id === selected}
                    onOpen={() => {
                      if (folded.length > 0) {
                        setExpanded((ids) => new Set(ids).add(event.event_id));
                      }
                      open(event.event_id);
                    }}
                  />
                </div>
              ))}
            </section>
          ))}
        </div>
      )}
      <div ref={endRef}>
        {cursor != null && (
          <Button
            size="xs"
            variant="ghost"
            disabled={loadingOlder}
            onClick={() => void loadOlder()}
          >
            {loadingOlder ? t("loadingOlder") : t("older")}
          </Button>
        )}
      </div>
    </div>
  );
}

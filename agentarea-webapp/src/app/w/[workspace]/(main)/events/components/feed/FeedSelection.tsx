"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "next/navigation";
import type { StreamEventDetailResponse } from "@/api/client/types.gen";
import { currentWorkspaceHeaders } from "@/lib/workspace-browser";
import { useFeedLive } from "./FeedLive";

/** An opened event as its route handler answered: the event, gone (null), or why it failed. */
export type FeedEventDetail =
  | { event: StreamEventDetailResponse | null }
  | { error: string };

interface FeedSelectionValue {
  /** The event open in the side panel (`?event=`). */
  selected: string | null;
  /** What was read for `selected` in this page, until a notice makes it stale. */
  detail: FeedEventDetail | undefined;
  /** The server rendered `selected` and nothing changed since: its panel stands. */
  serverRendered: boolean;
  /** Opens `eventId`, or closes the panel with `null`; `replace` for stepping through rows. */
  select: (eventId: string | null, replace?: boolean) => void;
  /** Reads `selected` again. */
  reload: () => void;
}

const FeedSelectionContext = createContext<FeedSelectionValue | null>(null);

/** A run of notices for the open event becomes one read. */
const RELOAD_MS = 300;

async function readEvent(eventId: string): Promise<FeedEventDetail> {
  try {
    const response = await fetch(`/api/events/${encodeURIComponent(eventId)}`, {
      headers: currentWorkspaceHeaders(),
      cache: "no-store",
    });
    if (response.ok) {
      return { event: (await response.json()) as StreamEventDetailResponse };
    }
    if (response.status === 404) return { event: null };
    const body = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    return { error: body?.detail ?? `HTTP ${response.status}` };
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

function eventInLocation(): string | null {
  return new URLSearchParams(window.location.search).get("event");
}

/**
 * The open event lives in `?event=`, changed in place with the History API,
 * so opening one reads that event alone rather than the whole page again.
 * The choice shows at once; the URL catches up. The server renders the event
 * of a URL that comes with one (`serverEvent`); any other is read from
 * `/api/events/{id}` here, and read again when the live feed says what the
 * platform did with it changed.
 */
export function FeedSelectionProvider({
  serverEvent,
  children,
}: {
  serverEvent: string | undefined;
  children: ReactNode;
}) {
  const urlEvent = useSearchParams().get("event");
  const [selected, setSelected] = useState(urlEvent);
  const { listen } = useFeedLive();
  const [details, setDetails] = useState<Record<string, FeedEventDetail>>({});
  const [serverStale, setServerStale] = useState(false);
  const reading = useRef(new Map<string, Promise<void>>());
  const serverRendered =
    selected !== null && selected === serverEvent && !serverStale;

  useEffect(() => setServerStale(false), [serverEvent]);

  const read = useCallback((eventId: string): Promise<void> => {
    const current = reading.current.get(eventId);
    if (current) return current;
    const done = readEvent(eventId).then((detail) => {
      reading.current.delete(eventId);
      setDetails((all) => ({ ...all, [eventId]: detail }));
    });
    reading.current.set(eventId, done);
    return done;
  }, []);

  useEffect(() => {
    if (selected && !serverRendered && !(selected in details)) {
      void read(selected);
    }
  }, [selected, serverRendered, details, read]);

  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const serverEventRef = useRef(serverEvent);
  serverEventRef.current = serverEvent;
  const knownRef = useRef<(eventId: string) => boolean>(() => false);
  knownRef.current = (eventId) =>
    eventId in details || (eventId === serverEvent && !serverStale);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stop = listen((message) => {
      if (message.type !== "processing") return;
      const { eventId } = message;
      if (eventId !== selectedRef.current) {
        if (eventId === serverEventRef.current) setServerStale(true);
        setDetails((all) => {
          if (!(eventId in all)) return all;
          const { [eventId]: _stale, ...rest } = all;
          return rest;
        });
        return;
      }
      clearTimeout(timer);
      timer = setTimeout(() => void read(eventId), RELOAD_MS);
    });
    return () => {
      stop();
      clearTimeout(timer);
    };
  }, [listen, read]);

  /** The last choice, and whether its URL is still to be written (and pushed). */
  const latest = useRef({ pending: false, push: false });
  // Back, forward and filter links move the URL. It is read rather than
  // `urlEvent`, which may still be a step behind a quick run of selections.
  useEffect(() => {
    if (!latest.current.pending) setSelected(eventInLocation());
  }, [urlEvent]);
  const chosen = useRef(selected);
  const select = useCallback(
    (eventId: string | null, replace = false) => {
      setSelected(eventId);
      chosen.current = eventId;
      latest.current = { pending: true, push: latest.current.push || !replace };
      const reading =
        eventId && !knownRef.current(eventId) ? read(eventId) : undefined;
      const write = () => {
        if (chosen.current !== eventId) return;
        const url = new URL(window.location.href);
        if (eventId) url.searchParams.set("event", eventId);
        else url.searchParams.delete("event");
        const next = `${url.pathname}${url.search}${url.hash}`;
        if (latest.current.push) window.history.pushState(null, "", next);
        else window.history.replaceState(null, "", next);
        latest.current = { pending: false, push: false };
      };
      // Next re-renders its router for a history change: once the panel is
      // drawn, so the two do not compete.
      if (reading) void reading.then(() => setTimeout(write));
      else setTimeout(write);
    },
    [read]
  );

  const reload = useCallback(() => {
    if (selectedRef.current) void read(selectedRef.current);
  }, [read]);

  return (
    <FeedSelectionContext.Provider
      value={{
        selected,
        detail: selected ? details[selected] : undefined,
        serverRendered,
        select,
        reload,
      }}
    >
      {children}
    </FeedSelectionContext.Provider>
  );
}

export function useFeedSelection(): FeedSelectionValue {
  const value = useContext(FeedSelectionContext);
  if (!value) throw new Error("useFeedSelection needs a FeedSelectionProvider");
  return value;
}

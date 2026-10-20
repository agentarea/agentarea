"use client";

import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import type { FeedEventResponse, Processing } from "@/api/client/types.gen";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { withWorkspaceQuery } from "@/lib/workspaces";

type Connection = "connecting" | "on" | "off";

const RETRY_MS = 3000;

export type LiveMessage =
  /** Subscribed, first or again: what arrived before it is read again. */
  | { type: "resync" }
  | { type: "recorded"; event: FeedEventResponse }
  | { type: "processing"; eventId: string; processing: Processing };

interface FeedLiveValue {
  connection: Connection;
  /** Calls `listener` with every message from now on; returns the unsubscribe. */
  listen: (listener: (message: LiveMessage) => void) => () => void;
}

const FeedLiveContext = createContext<FeedLiveValue | null>(null);

/**
 * One SSE connection per page to the workspace's live feed: what arrived
 * (`event.recorded`) and what the platform did with it since
 * (`event.processing`). The browser reconnects on its own.
 */
export function FeedLiveProvider({
  query,
  children,
}: {
  /** The feed's filters as the live endpoint reads them. */
  query: string;
  children: ReactNode;
}) {
  const slug = useWorkspaceSlug();
  const [connection, setConnection] = useState<Connection>("connecting");
  const listeners = useRef(new Set<(message: LiveMessage) => void>());

  useEffect(() => {
    const url = withWorkspaceQuery(
      `/api/sse/events/live${query ? `?${query}` : ""}`,
      slug
    );
    const emit = (message: LiveMessage) => {
      for (const listener of listeners.current) listener(message);
    };
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      const current = new EventSource(url);
      source = current;
      // Read the page again once subscribed: an event that arrived between
      // the server's read and this subscription would otherwise be missed.
      current.onopen = () => {
        setConnection("on");
        emit({ type: "resync" });
      };
      current.onerror = () => {
        setConnection("off");
        // A refused response (the API restarting) closes it for good; the
        // browser retries only a connection that dropped.
        if (current.readyState === EventSource.CLOSED) {
          retry = setTimeout(connect, RETRY_MS);
        }
      };
      current.addEventListener("event.recorded", (frame) => {
        emit({
          type: "recorded",
          event: JSON.parse((frame as MessageEvent).data) as FeedEventResponse,
        });
      });
      current.addEventListener("event.processing", (frame) => {
        const data = JSON.parse((frame as MessageEvent).data) as {
          event_id: string;
          processing: Processing;
        };
        emit({
          type: "processing",
          eventId: data.event_id,
          processing: data.processing,
        });
      });
    };
    connect();
    return () => {
      clearTimeout(retry);
      source?.close();
    };
  }, [query, slug]);

  const value: FeedLiveValue = {
    connection,
    listen: (listener) => {
      listeners.current.add(listener);
      return () => {
        listeners.current.delete(listener);
      };
    },
  };
  return (
    <FeedLiveContext.Provider value={value}>
      {children}
    </FeedLiveContext.Provider>
  );
}

export function useFeedLive(): FeedLiveValue {
  const value = useContext(FeedLiveContext);
  if (!value) throw new Error("useFeedLive needs a FeedLiveProvider");
  return value;
}

export function LiveIndicator() {
  const t = useTranslations("EventsPage.live");
  const { connection } = useFeedLive();
  const kind =
    connection === "on" ? "active" : connection === "off" ? "off" : "running";
  return (
    <StatusIndicator size="sm" kind={kind} className="mr-2">
      {t(connection)}
    </StatusIndicator>
  );
}

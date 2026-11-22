"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useFeedLive } from "@/app/w/[workspace]/(main)/events/components/feed/FeedLive";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { Canvas, OrgSource } from "../utils/canvasState";
import { diffTasks, type Happening } from "../utils/liveDiff";
import type { CanvasTask, CanvasTrigger } from "./canvasTypes";

export type AgentFlash = { tasks: number; cost: number; at: number };

export type CanvasLive = {
  happenings: Happening[];
  /** Arrow id → when a pulse started along it. */
  pulses: ReadonlyMap<string, number>;
  /** Agent id → what just landed on it. */
  flashes: ReadonlyMap<string, AgentFlash>;
};

const REFRESH_MS = 20_000;
const AFTER_EVENT_MS = [1_500, 10_000];
const FLASH_MS = 4_500;
const MAX_HAPPENINGS = 60;

/**
 * The canvas's live layer. Events come over the workspace feed as they are
 * recorded; tasks and spend come from re-reading the page — right after an
 * event made tasks, and on a slow beat while the tab is visible — and are
 * diffed against the previous read.
 */
export function useCanvasLive({
  canvas,
  tasks,
  triggers,
}: {
  canvas: Canvas | null;
  tasks: CanvasTask[];
  triggers: CanvasTrigger[];
}): CanvasLive {
  const router = useWorkspaceRouter();
  const { listen } = useFeedLive();
  const [happenings, setHappenings] = useState<Happening[]>([]);
  const [pulses, setPulses] = useState<Map<string, number>>(new Map());
  const [flashes, setFlashes] = useState<Map<string, AgentFlash>>(new Map());
  const canvasRef = useRef(canvas);
  canvasRef.current = canvas;
  const triggersRef = useRef(triggers);
  triggersRef.current = triggers;
  const previousTasks = useRef(tasks);

  const record = useCallback((items: Happening[]) => {
    if (items.length === 0) return;
    setHappenings((current) =>
      [...[...items].reverse(), ...current].slice(0, MAX_HAPPENINGS)
    );
  }, []);

  const pulse = useCallback((source: OrgSource, agentId: string) => {
    const current = canvasRef.current;
    if (!current) return;
    const from = current.tiles.find(
      (tile) => tile.kind === "source" && tile.source === source
    );
    const to = current.tiles.find(
      (tile) => tile.kind === "agent" && tile.agentId === agentId
    );
    const link =
      from &&
      to &&
      current.links.find((l) => l.from === from.id && l.to === to.id);
    if (!link) return;
    const at = Date.now();
    setPulses((map) => new Map(map).set(link.id, at));
    window.setTimeout(
      () =>
        setPulses((map) => {
          if (map.get(link.id) !== at) return map;
          const next = new Map(map);
          next.delete(link.id);
          return next;
        }),
      FLASH_MS
    );
  }, []);

  const flash = useCallback(
    (agentId: string, change: { tasks?: number; cost?: number }) => {
      const at = Date.now();
      setFlashes((map) => {
        const old = map.get(agentId);
        const fresh = old && at - old.at < FLASH_MS ? old : undefined;
        return new Map(map).set(agentId, {
          tasks: (fresh?.tasks ?? 0) + (change.tasks ?? 0),
          cost: (fresh?.cost ?? 0) + (change.cost ?? 0),
          at,
        });
      });
      window.setTimeout(
        () =>
          setFlashes((map) => {
            if (map.get(agentId)?.at !== at) return map;
            const next = new Map(map);
            next.delete(agentId);
            return next;
          }),
        FLASH_MS
      );
    },
    []
  );

  useEffect(() => {
    const previous = previousTasks.current;
    previousTasks.current = tasks;
    if (previous === tasks) return;
    const changes = diffTasks(previous, tasks, Date.now());
    for (const change of changes) {
      if (change.kind === "task") {
        pulse(change.source, change.agentId);
        flash(change.agentId, { tasks: 1 });
      } else if (change.kind === "cost") {
        flash(change.agentId, { cost: change.delta });
      }
    }
    record(changes);
  }, [tasks, pulse, flash, record]);

  useEffect(() => {
    const timers: number[] = [];
    const refreshSoon = () => {
      for (const delay of AFTER_EVENT_MS) {
        timers.push(window.setTimeout(() => router.refresh(), delay));
      }
    };
    const unlisten = listen((message) => {
      if (message.type === "recorded") {
        const event = message.event;
        const agentIds = [
          ...new Set(
            triggersRef.current
              .filter((t) => t.streamId && t.streamId === event.stream_id)
              .map((t) => t.agentId)
          ),
        ];
        for (const agentId of agentIds) {
          pulse("event", agentId);
          flash(agentId, {});
        }
        record([
          {
            kind: "event",
            id: `event:${event.event_id}`,
            at: Date.now(),
            summary: event.sender ? `${event.kind} · ${event.sender}` : event.kind,
            agentIds,
          },
        ]);
      } else if (
        message.type === "processing" &&
        (message.processing.tasks?.length ?? 0) > 0
      ) {
        refreshSoon();
      }
    });
    const beat = window.setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, REFRESH_MS);
    return () => {
      unlisten();
      window.clearInterval(beat);
      timers.forEach((timer) => window.clearTimeout(timer));
    };
  }, [listen, router, pulse, flash, record]);

  return { happenings, pulses, flashes };
}

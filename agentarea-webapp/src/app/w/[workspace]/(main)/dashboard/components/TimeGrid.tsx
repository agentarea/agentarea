"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import type { ScheduledRun } from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";
import {
  initialScrollHour,
  layoutLanes,
  minuteOfDay,
  minuteOffset,
  type LaneOverflow,
} from "./calendar";
import { RunChip, runHref, runKey, runName } from "./RunChip";

const HOUR_HEIGHT = 44;
/** Runs have no duration; a block covers this much of the axis. */
const BLOCK_MINUTES = 30;
const BLOCK_HEIGHT = minuteOffset(BLOCK_MINUTES, HOUR_HEIGHT);
const MAX_LANES = 4;
const HOURS = Array.from({ length: 24 }, (_, h) => h);

export type TimeGridFormats = {
  time: (iso: string) => string;
  hour: (hour: number) => string;
  weekday: (d: Date) => string;
  dayLabel: (d: Date) => string;
};

function useMinuteClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

function laneStyle(minute: number, lane: number, lanes: number) {
  return {
    top: minuteOffset(minute, HOUR_HEIGHT),
    height: BLOCK_HEIGHT,
    left: `calc(${(lane * 100) / lanes}% + 2px)`,
    width: `calc(${100 / lanes}% - 4px)`,
  };
}

function RunBlock({
  run,
  style,
  past,
  formats,
  date,
}: {
  run: ScheduledRun;
  style: CSSProperties;
  past: boolean;
  formats: TimeGridFormats;
  date: string;
}) {
  const name = runName(run);
  return (
    <Link
      href={runHref(run)}
      style={style}
      title={`${formats.time(run.fires_at)} ${name}`}
      aria-label={`${date} ${formats.time(run.fires_at)} ${name}`}
      className={cn(
        "absolute z-[1] flex min-w-0 items-center gap-1.5 overflow-hidden rounded-[5px] border px-1.5 text-[11px] leading-none transition-colors",
        past
          ? "border-zinc-200 bg-muted/60 text-muted-foreground hover:bg-muted dark:border-zinc-700"
          : "border-primary/30 bg-primary/10 text-foreground hover:bg-primary/15 dark:bg-primary/20 dark:hover:bg-primary/25"
      )}
    >
      <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
        {formats.time(run.fires_at)}
      </span>
      <span className="min-w-0 flex-1 truncate font-medium">{run.title}</span>
      {run.agent_name && (
        <AgentAvatar
          agent={{ id: run.agent_id, name: run.agent_name }}
          size="xs"
        />
      )}
    </Link>
  );
}

function OverflowBlock({
  overflow,
  formats,
  date,
}: {
  overflow: LaneOverflow<ScheduledRun>;
  formats: TimeGridFormats;
  date: string;
}) {
  const t = useTranslations("DashboardPage");
  const label = t("moreRuns", { count: overflow.items.length });
  return (
    <Popover>
      <PopoverTrigger
        style={laneStyle(overflow.minute, overflow.lane, overflow.lanes)}
        aria-label={label}
        className="absolute z-[1] rounded-[5px] border border-dashed border-zinc-300 bg-background px-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted dark:border-zinc-600"
      >
        +{overflow.items.length}
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-64 flex-col gap-1 p-2">
        {overflow.items.map((run) => (
          <RunChip
            key={runKey(run)}
            run={run}
            time={formats.time}
            date={date}
            withAgent
          />
        ))}
      </PopoverContent>
    </Popover>
  );
}

/**
 * Today on a 24-hour axis, like a calendar's day view. Opens scrolled to the
 * current hour, or to the first run when it is earlier.
 */
export function TimeGrid({
  runs,
  formats,
  note,
}: {
  /** Today's runs. */
  runs: ScheduledRun[];
  formats: TimeGridFormats;
  /** Shown over the grid, e.g. when the day has no runs. */
  note?: ReactNode;
}) {
  const now = useMinuteClock();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [startHour] = useState(() => initialScrollHour(new Date(), runs));
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = Math.max(0, startHour * HOUR_HEIGHT - 4);
    }
  }, [startHour]);

  const date = formats.dayLabel(now);
  const { blocks, overflows } = layoutLanes(runs, BLOCK_MINUTES, MAX_LANES);

  return (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        className="h-[460px] overflow-y-auto md:h-auto md:min-h-0 md:flex-1"
      >
        <div className="flex" style={{ height: 24 * HOUR_HEIGHT }}>
          <div className="relative w-14 shrink-0" aria-hidden>
            {HOURS.map((h) => (
              <span
                key={h}
                className={cn(
                  "absolute right-2 font-mono text-[10.5px] tabular-nums text-muted-foreground",
                  h > 0 && "-translate-y-1/2"
                )}
                style={{ top: h * HOUR_HEIGHT }}
              >
                {formats.hour(h)}
              </span>
            ))}
          </div>

          <div className="relative flex-1 border-l border-zinc-200 dark:border-zinc-700">
            {HOURS.map((h) => (
              <div
                key={h}
                aria-hidden
                className="pointer-events-none absolute inset-x-0 border-t border-zinc-100 dark:border-zinc-800"
                style={{ top: h * HOUR_HEIGHT }}
              />
            ))}
            {blocks.map((b) => (
              <RunBlock
                key={runKey(b.item)}
                run={b.item}
                style={laneStyle(b.minute, b.lane, b.lanes)}
                past={new Date(b.item.fires_at) < now}
                formats={formats}
                date={date}
              />
            ))}
            {overflows.map((o) => (
              <OverflowBlock
                key={o.minute}
                overflow={o}
                formats={formats}
                date={date}
              />
            ))}
            <div
              className="pointer-events-none absolute inset-x-0 z-[2] h-px bg-primary"
              style={{ top: minuteOffset(minuteOfDay(now), HOUR_HEIGHT) }}
              aria-hidden
            >
              <span className="absolute -left-1 -top-[3.5px] h-2 w-2 rounded-full bg-primary" />
            </div>
          </div>
        </div>
      </div>

      {note && (
        <div className="pointer-events-none absolute inset-x-0 top-3 z-[4] flex justify-center px-6">
          <div className="pointer-events-auto rounded-md border border-zinc-200 bg-background/95 px-3 py-2 text-center text-[12.5px] text-muted-foreground shadow-sm dark:border-zinc-700">
            {note}
          </div>
        </div>
      )}
    </div>
  );
}

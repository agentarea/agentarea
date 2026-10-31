// Lays scheduled runs out by the viewer's local day: today and this
// Monday-first week on an hour axis, and the weeks of the current month.

export type CalendarDay<T> = {
  date: Date;
  isToday: boolean;
  isPast: boolean;
  /** False for the leading and trailing days a month grid borrows. */
  inMonth: boolean;
  items: T[];
};

export function dayKey(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${m}-${d}`;
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

function mondayOf(date: Date): Date {
  return addDays(date, -((date.getDay() + 6) % 7));
}

function byFiresAt<T extends { fires_at: string }>(items: T[]): T[] {
  return [...items].sort((a, b) => a.fires_at.localeCompare(b.fires_at));
}

/** Whole weeks from the Monday of `from` through the week that holds `to`. */
function buildWeeks<T extends { fires_at: string }>(
  items: T[],
  now: Date,
  from: Date,
  to: Date
): CalendarDay<T>[][] {
  const today = addDays(now, 0);
  const monday = mondayOf(from);
  const span = Math.round((to.getTime() - monday.getTime()) / 86_400_000) + 1;
  const weekCount = Math.ceil(span / 7);

  const byDay = new Map<string, T[]>();
  for (const item of byFiresAt(items)) {
    const key = dayKey(new Date(item.fires_at));
    const bucket = byDay.get(key);
    if (bucket) bucket.push(item);
    else byDay.set(key, [item]);
  }

  const todayKey = dayKey(today);
  return Array.from({ length: weekCount }, (_, w) =>
    Array.from({ length: 7 }, (_, d) => {
      const date = addDays(monday, w * 7 + d);
      const key = dayKey(date);
      return {
        date,
        isToday: key === todayKey,
        isPast: date < today,
        inMonth: date.getMonth() === today.getMonth(),
        items: byDay.get(key) ?? [],
      };
    })
  );
}

/** Monday through Sunday of the current week. */
export function buildWeekDays<T extends { fires_at: string }>(
  items: T[],
  now: Date
): CalendarDay<T>[] {
  return buildWeeks(items, now, now, now)[0];
}

/** The weeks that hold any day of the current month. */
export function buildMonthWeeks<T extends { fires_at: string }>(
  items: T[],
  now: Date
): CalendarDay<T>[][] {
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  const last = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return buildWeeks(items, now, first, last);
}

/** The first run at or after `from`, discrete or frequent. */
export function firstRunFrom<
  R extends { fires_at: string },
  F extends { next_run_at: string },
>(runs: R[], frequent: F[], from: Date): R | F | null {
  const later = [
    ...runs.map((item) => ({ item, at: new Date(item.fires_at) })),
    ...frequent.map((item) => ({ item, at: new Date(item.next_run_at) })),
  ]
    .filter(({ at }) => at >= from)
    .sort((a, b) => a.at.getTime() - b.at.getTime());
  return later[0]?.item ?? null;
}

export type TodayAgenda<R, F> = {
  /** Today's runs in time order. */
  runs: R[];
  /** Frequent schedules whose next run falls today. */
  frequent: F[];
  /** The first run after today, for an empty day. */
  next: R | F | null;
};

export function buildTodayAgenda<
  R extends { fires_at: string },
  F extends { next_run_at: string },
>(runs: R[], frequent: F[], now: Date): TodayAgenda<R, F> {
  const tomorrow = addDays(now, 1);
  return {
    runs: byFiresAt(runs).filter(
      (r) => dayKey(new Date(r.fires_at)) === dayKey(now)
    ),
    frequent: frequent.filter((f) => new Date(f.next_run_at) < tomorrow),
    next: firstRunFrom(runs, frequent, tomorrow),
  };
}

/** Minutes since the viewer's local midnight. */
export function minuteOfDay(date: Date): number {
  return date.getHours() * 60 + date.getMinutes();
}

export function minuteOffset(minute: number, hourHeight: number): number {
  return (minute / 60) * hourHeight;
}

/**
 * The hour a time grid opens at: the current hour, or the hour of the view's
 * first run when that comes earlier.
 */
export function initialScrollHour(
  now: Date,
  runs: { fires_at: string }[]
): number {
  const first = Math.min(
    minuteOfDay(now),
    ...runs.map((r) => minuteOfDay(new Date(r.fires_at)))
  );
  return Math.floor(first / 60);
}

export type LaneBlock<T> = {
  item: T;
  minute: number;
  lane: number;
  /** Lanes the block's cluster is split into. */
  lanes: number;
};

export type LaneOverflow<T> = {
  minute: number;
  lane: number;
  lanes: number;
  items: T[];
};

function assignLanes(minutes: number[], blockMinutes: number, cap: number) {
  const laneEnds: number[] = [];
  return minutes.map((minute) => {
    let lane = laneEnds.findIndex((end) => end <= minute);
    if (lane === -1 && laneEnds.length < cap) lane = laneEnds.push(0) - 1;
    if (lane !== -1) laneEnds[lane] = minute + blockMinutes;
    return lane;
  });
}

/**
 * Runs have no duration: each is drawn as a block `blockMinutes` tall from its
 * start. Blocks that overlap form a cluster and sit side by side in lanes. A
 * cluster that needs more than `maxLanes` keeps its last lane for the runs that
 * do not fit, grouped into one overflow per overlapping stretch.
 */
export function layoutLanes<T extends { fires_at: string }>(
  items: T[],
  blockMinutes: number,
  maxLanes: number
): { blocks: LaneBlock<T>[]; overflows: LaneOverflow<T>[] } {
  const timed = byFiresAt(items).map((item) => ({
    item,
    minute: minuteOfDay(new Date(item.fires_at)),
  }));

  const clusters: (typeof timed)[] = [];
  let end = -Infinity;
  for (const entry of timed) {
    if (entry.minute < end) clusters[clusters.length - 1].push(entry);
    else clusters.push([entry]);
    end = Math.max(end, entry.minute + blockMinutes);
  }

  const blocks: LaneBlock<T>[] = [];
  const overflows: LaneOverflow<T>[] = [];
  for (const cluster of clusters) {
    const minutes = cluster.map((e) => e.minute);
    const free = assignLanes(minutes, blockMinutes, Infinity);
    const needed = Math.max(...free) + 1;
    if (needed <= maxLanes) {
      cluster.forEach((e, i) =>
        blocks.push({ ...e, lane: free[i], lanes: needed })
      );
      continue;
    }
    const capped = assignLanes(minutes, blockMinutes, maxLanes - 1);
    let open: LaneOverflow<T> | null = null;
    cluster.forEach((e, i) => {
      if (capped[i] !== -1) {
        blocks.push({ ...e, lane: capped[i], lanes: maxLanes });
      } else if (open && e.minute < open.minute + blockMinutes) {
        open.items.push(e.item);
      } else {
        open = {
          minute: e.minute,
          lane: maxLanes - 1,
          lanes: maxLanes,
          items: [e.item],
        };
        overflows.push(open);
      }
    });
  }
  return { blocks, overflows };
}

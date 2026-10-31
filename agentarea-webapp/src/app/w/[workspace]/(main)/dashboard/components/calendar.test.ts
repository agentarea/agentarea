import { describe, expect, it } from "vitest";
import {
  buildMonthWeeks,
  buildTodayAgenda,
  buildWeekDays,
  dayKey,
  initialScrollHour,
  layoutLanes,
  minuteOffset,
} from "./calendar";

// Local-time constructors keep the cases independent of the machine's zone.
const at = (d: number, h = 0, m = 0) => new Date(2026, 9, d, h, m);
const run = (d: number, h: number, m = 0) => ({
  fires_at: at(d, h, m).toISOString(),
});
const frequent = (d: number, h: number) => ({
  next_run_at: at(d, h).toISOString(),
});

// 2026-10-02 is a Friday.
const now = at(2, 15, 30);

describe("buildWeekDays", () => {
  it("is Monday through Sunday of the current week", () => {
    const days = buildWeekDays([], now);
    expect(days.map((d) => dayKey(d.date))).toEqual([
      "2026-09-28",
      "2026-09-29",
      "2026-09-30",
      "2026-10-01",
      "2026-10-02",
      "2026-10-03",
      "2026-10-04",
    ]);
  });

  it("marks today and the days before it", () => {
    const days = buildWeekDays([], now);
    expect(days.filter((d) => d.isToday).map((d) => dayKey(d.date))).toEqual([
      "2026-10-02",
    ]);
    expect(days.filter((d) => d.isPast)).toHaveLength(4);
  });

  it("puts each run on its local day in time order and drops the rest", () => {
    const days = buildWeekDays([run(3, 20), run(3, 9), run(30, 9)], now);
    const byKey = new Map(days.map((d) => [dayKey(d.date), d.items]));
    expect(byKey.get("2026-10-03")?.map((i) => i.fires_at)).toEqual([
      at(3, 9).toISOString(),
      at(3, 20).toISOString(),
    ]);
    expect(days.flatMap((d) => d.items)).toHaveLength(2);
  });
});

describe("buildMonthWeeks", () => {
  it("covers the month in whole Monday-first weeks", () => {
    const weeks = buildMonthWeeks([], now);
    // October 2026 runs Thu 1 → Sat 31: Mon 28 Sep → Sun 1 Nov.
    expect(weeks).toHaveLength(5);
    expect(dayKey(weeks[0][0].date)).toBe("2026-09-28");
    expect(dayKey(weeks[4][6].date)).toBe("2026-11-01");
  });

  it("flags the borrowed days outside the month", () => {
    const outside = buildMonthWeeks([], now)
      .flat()
      .filter((d) => !d.inMonth)
      .map((d) => dayKey(d.date));
    expect(outside).toEqual([
      "2026-09-28",
      "2026-09-29",
      "2026-09-30",
      "2026-11-01",
    ]);
  });
});

describe("buildTodayAgenda", () => {
  it("lists today's runs in time order", () => {
    const agenda = buildTodayAgenda(
      [run(2, 18), run(2, 9), run(3, 9)],
      [],
      now
    );
    expect(agenda.runs).toEqual([run(2, 9), run(2, 18)]);
  });

  it("keeps the frequent schedules that fire today", () => {
    const agenda = buildTodayAgenda([], [frequent(2, 16), frequent(5, 9)], now);
    expect(agenda.frequent).toEqual([frequent(2, 16)]);
  });

  it("names the first run after today for an empty day", () => {
    const agenda = buildTodayAgenda(
      [run(6, 9), run(4, 12)],
      [frequent(4, 8)],
      now
    );
    expect(agenda.runs).toEqual([]);
    expect(agenda.next).toEqual(frequent(4, 8));
  });

  it("has no next run when nothing is scheduled", () => {
    expect(buildTodayAgenda([], [], now).next).toBeNull();
  });
});

describe("time axis", () => {
  it("places a minute on the hour scale", () => {
    expect(minuteOffset(90, 48)).toBe(72);
    expect(minuteOffset(0, 48)).toBe(0);
  });

  it("opens at the current hour, or at an earlier first run", () => {
    expect(initialScrollHour(now, [run(2, 18)])).toBe(15);
    expect(initialScrollHour(now, [run(2, 18), run(2, 7, 45)])).toBe(7);
    expect(initialScrollHour(now, [])).toBe(15);
  });
});

describe("layoutLanes", () => {
  const lanes = (items: { fires_at: string }[], max = 3) =>
    layoutLanes(items, 30, max);

  it("gives runs that do not overlap the full width", () => {
    const { blocks, overflows } = lanes([run(2, 9), run(2, 10)]);
    expect(blocks.map((b) => [b.minute, b.lane, b.lanes])).toEqual([
      [540, 0, 1],
      [600, 0, 1],
    ]);
    expect(overflows).toEqual([]);
  });

  it("puts overlapping runs side by side and reuses a lane once it frees", () => {
    const { blocks } = lanes([run(2, 9), run(2, 9, 10), run(2, 9, 35)]);
    expect(blocks.map((b) => [b.minute, b.lane, b.lanes])).toEqual([
      [540, 0, 2],
      [550, 1, 2],
      [575, 0, 2],
    ]);
  });

  it("keeps the last lane for what does not fit", () => {
    const { blocks, overflows } = lanes([
      run(2, 9),
      run(2, 9),
      run(2, 9, 5),
      run(2, 9, 10),
      run(2, 14),
    ]);
    expect(blocks.map((b) => [b.minute, b.lane, b.lanes])).toEqual([
      [540, 0, 3],
      [540, 1, 3],
      [840, 0, 1],
    ]);
    expect(overflows).toEqual([
      {
        minute: 545,
        lane: 2,
        lanes: 3,
        items: [run(2, 9, 5), run(2, 9, 10)],
      },
    ]);
  });
});

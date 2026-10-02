import { describe, expect, it } from "vitest";
import { buildCalendarWeeks, dayKey } from "./calendar";

// Local-time constructors keep the cases independent of the machine's zone.
const at = (d: number, h = 0, m = 0) => new Date(2026, 9, d, h, m);
const run = (d: number, h: number, m = 0) => ({
  fires_at: at(d, h, m).toISOString(),
});

describe("buildCalendarWeeks", () => {
  // 2026-10-02 is a Friday.
  const now = at(2, 15, 30);

  it("starts on the Monday of the current week", () => {
    const weeks = buildCalendarWeeks([], now, 21);
    expect(dayKey(weeks[0][0].date)).toBe("2026-09-28");
    expect(weeks.every((w) => w.length === 7)).toBe(true);
  });

  it("covers the whole horizon in full weeks", () => {
    const weeks = buildCalendarWeeks([], now, 21);
    // Fri 2 Oct + 21 days = Fri 23 Oct, inside the fourth week.
    expect(weeks).toHaveLength(4);
    expect(dayKey(weeks[3][6].date)).toBe("2026-10-25");
  });

  it("marks today and the days before it", () => {
    const days = buildCalendarWeeks([], now, 7).flat();
    const today = days.find((d) => d.isToday);
    expect(today && dayKey(today.date)).toBe("2026-10-02");
    expect(days.filter((d) => d.isPast).map((d) => dayKey(d.date))).toEqual([
      "2026-09-28",
      "2026-09-29",
      "2026-09-30",
      "2026-10-01",
    ]);
  });

  it("puts each run on its local day in time order", () => {
    const days = buildCalendarWeeks(
      [run(3, 20), run(3, 9), run(5, 8, 15)],
      now,
      7
    ).flat();
    const byKey = new Map(days.map((d) => [dayKey(d.date), d.items]));
    expect(byKey.get("2026-10-03")?.map((i) => i.fires_at)).toEqual([
      at(3, 9).toISOString(),
      at(3, 20).toISOString(),
    ]);
    expect(byKey.get("2026-10-05")).toHaveLength(1);
    expect(byKey.get("2026-10-04")).toEqual([]);
  });

  it("drops runs outside the grid", () => {
    const days = buildCalendarWeeks([run(30, 9)], now, 7).flat();
    expect(days.every((d) => d.items.length === 0)).toBe(true);
  });
});

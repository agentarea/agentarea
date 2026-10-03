// Lays scheduled runs out on a Monday-first month-style grid, bucketed by the
// viewer's local day.

export type CalendarDay<T> = {
  date: Date;
  isToday: boolean;
  isPast: boolean;
  items: T[];
};

export function dayKey(date: Date): string {
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** Weeks from this Monday through the week that holds `now + horizonDays`. */
export function buildCalendarWeeks<T extends { fires_at: string }>(
  items: T[],
  now: Date,
  horizonDays: number
): CalendarDay<T>[][] {
  const today = addDays(now, 0);
  const monday = addDays(today, -((today.getDay() + 6) % 7));
  const last = addDays(today, horizonDays);
  const span =
    Math.round((last.getTime() - monday.getTime()) / 86_400_000) + 1;
  const weekCount = Math.ceil(span / 7);

  const byDay = new Map<string, T[]>();
  for (const item of [...items].sort((a, b) =>
    a.fires_at.localeCompare(b.fires_at)
  )) {
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
        items: byDay.get(key) ?? [],
      };
    })
  );
}

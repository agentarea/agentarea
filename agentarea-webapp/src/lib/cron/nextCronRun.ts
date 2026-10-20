/**
 * When a cron schedule next comes due, worked out on the client.
 *
 * The trigger API carries a `next_run_time` it never fills in, so a schedule's
 * next run has to come from its expression and timezone. Five fields (minute,
 * hour, day of month, month, day of week), or six with leading seconds, which
 * are dropped: schedules here fire on the minute.
 */

type Field = { min: number; max: number; names?: Record<string, number> };

const MONTH_NAMES: Record<string, number> = {
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  may: 5,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  oct: 10,
  nov: 11,
  dec: 12,
};
const DAY_NAMES: Record<string, number> = {
  sun: 0,
  mon: 1,
  tue: 2,
  wed: 3,
  thu: 4,
  fri: 5,
  sat: 6,
};

const FIELDS: Field[] = [
  { min: 0, max: 59 }, // minute
  { min: 0, max: 23 }, // hour
  { min: 1, max: 31 }, // day of month
  { min: 1, max: 12, names: MONTH_NAMES }, // month
  { min: 0, max: 7, names: DAY_NAMES }, // day of week; 7 is Sunday too
];

/** How far ahead to look before calling a schedule one that never fires. */
const SEARCH_DAYS = 366 * 5;

function parseValue(raw: string, field: Field): number {
  const named = field.names?.[raw.toLowerCase()];
  const value = named ?? Number(raw);
  if (!Number.isInteger(value) || value < field.min || value > field.max) {
    throw new Error(`cron value out of range: ${raw}`);
  }
  return value;
}

/** One field as the set of values it allows, and whether it was "*". */
function parseField(source: string, field: Field) {
  const values = new Set<number>();
  for (const part of source.split(",")) {
    const [range, stepRaw] = part.split("/");
    const step = stepRaw === undefined ? 1 : Number(stepRaw);
    if (!Number.isInteger(step) || step < 1) {
      throw new Error(`cron step out of range: ${part}`);
    }
    let from: number;
    let to: number;
    if (range === "*") {
      from = field.min;
      to = field.max;
    } else if (range.includes("-")) {
      const [a, b] = range.split("-");
      from = parseValue(a, field);
      to = parseValue(b, field);
    } else {
      from = parseValue(range, field);
      // "5/15" runs from 5 to the end of the range.
      to = stepRaw === undefined ? from : field.max;
    }
    if (from > to) throw new Error(`cron range reversed: ${part}`);
    for (let value = from; value <= to; value += step) values.add(value);
  }
  return { values, any: source === "*" };
}

// One formatter per zone: building one is the expensive part, and a busy
// schedule asks for hundreds of readings while it searches.
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(timeZone: string) {
  let formatter = formatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
    });
    formatters.set(timeZone, formatter);
  }
  return formatter;
}

/** The wall-clock reading of an instant in a timezone. */
function wallClock(instant: Date, timeZone: string) {
  const parts = formatterFor(timeZone).formatToParts(instant);
  const get = (type: string) =>
    Number(parts.find((part) => part.type === type)?.value);
  return {
    year: get("year"),
    month: get("month"),
    day: get("day"),
    hour: get("hour"),
    minute: get("minute"),
  };
}

/** The instant a wall-clock time in a timezone names. */
function fromWallClock(
  year: number,
  month: number,
  day: number,
  hour: number,
  minute: number,
  timeZone: string
): Date {
  const asUtc = Date.UTC(year, month - 1, day, hour, minute);
  // The zone's offset at a guess, then again at the corrected instant, so a
  // time just across a DST change lands on the right side of it.
  let instant = asUtc;
  for (let i = 0; i < 2; i++) {
    const seen = wallClock(new Date(instant), timeZone);
    const seenUtc = Date.UTC(
      seen.year,
      seen.month - 1,
      seen.day,
      seen.hour,
      seen.minute
    );
    instant += asUtc - seenUtc;
  }
  return new Date(instant);
}

function validTimeZone(timeZone: string | null | undefined): string {
  if (!timeZone) return "UTC";
  try {
    new Intl.DateTimeFormat("en-US", { timeZone });
    return timeZone;
  } catch {
    return "UTC";
  }
}

/**
 * The first time after `after` that `expression` fires in `timeZone`, or null
 * when the expression cannot be read or never fires within five years.
 */
export function nextCronRun(
  expression: string | null | undefined,
  timeZone: string | null | undefined,
  after: Date
): Date | null {
  if (!expression) return null;
  let fields = expression.trim().split(/\s+/);
  if (fields.length === 6) fields = fields.slice(1);
  if (fields.length !== 5) return null;

  let minutes, hours, days, months, weekdays;
  try {
    [minutes, hours, days, months, weekdays] = fields.map((source, index) =>
      parseField(source, FIELDS[index])
    );
  } catch {
    return null;
  }
  if (weekdays.values.has(7)) weekdays.values.add(0);

  const zone = validTimeZone(timeZone);
  const start = wallClock(after, zone);
  const sortedHours = [...hours.values].sort((a, b) => a - b);
  const sortedMinutes = [...minutes.values].sort((a, b) => a - b);

  // Walk the calendar in the trigger's own timezone, a day at a time.
  for (let offset = 0; offset <= SEARCH_DAYS; offset++) {
    const date = new Date(
      Date.UTC(start.year, start.month - 1, start.day + offset)
    );
    const year = date.getUTCFullYear();
    const month = date.getUTCMonth() + 1;
    const day = date.getUTCDate();
    if (!months.values.has(month)) continue;

    // Classic cron: with both day fields restricted, either one matching is
    // enough; with one of them "*", only the other one counts.
    const domMatch = days.values.has(day);
    const dowMatch = weekdays.values.has(date.getUTCDay());
    const dayMatches =
      days.any && weekdays.any
        ? true
        : days.any
          ? dowMatch
          : weekdays.any
            ? domMatch
            : domMatch || dowMatch;
    if (!dayMatches) continue;

    for (const hour of sortedHours) {
      for (const minute of sortedMinutes) {
        const candidate = fromWallClock(year, month, day, hour, minute, zone);
        if (candidate.getTime() > after.getTime()) return candidate;
      }
    }
  }
  return null;
}

import {
  addDays,
  addHours,
  format,
  isValid,
  nextMonday,
  parse,
  startOfDay,
  startOfHour,
  type Locale,
} from "date-fns";

const pad = (n: number) => String(n).padStart(2, "0");

/** The viewer's local wall time, as a `datetime-local` input holds it. */
export function toLocalInputValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Null for an empty or unreadable value. */
export function fromLocalInputValue(value: string): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** The earliest moment a run can be booked for: the next whole minute. */
export function earliestScheduleTime(now: Date): Date {
  const next = new Date(now);
  next.setSeconds(0, 0);
  next.setMinutes(next.getMinutes() + 1);
  return next;
}

/** The time a fresh schedule starts from: the next whole hour. */
export function defaultScheduleTime(now: Date): Date {
  return addHours(startOfHour(now), 1);
}

/** A day as the viewer types it: the locale's short date, e.g. 31.10.2026. */
export function formatScheduleDay(date: Date, locale: Locale): string {
  return format(date, "P", { locale });
}

/** A wall time as the viewer types it, on a 24-hour clock. */
export function formatScheduleClock(date: Date): string {
  return format(date, "HH:mm");
}

/** The start of the typed day, or null when it is not a date in that locale. */
export function parseScheduleDay(text: string, locale: Locale): Date | null {
  const day = parse(text.trim(), "P", new Date(), { locale });
  return isValid(day) ? startOfDay(day) : null;
}

/** Hours and minutes of a typed `9:30` or `09:30`, or null. */
export function parseScheduleClock(
  text: string
): { hours: number; minutes: number } | null {
  const match = /^(\d{1,2})[:.](\d{2})$/.exec(text.trim());
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? { hours, minutes } : null;
}

/** That day at that wall time. */
export function atClock(
  day: Date,
  clock: { hours: number; minutes: number }
): Date {
  const date = startOfDay(day);
  date.setHours(clock.hours, clock.minutes);
  return date;
}

export type SchedulePreset = "inOneHour" | "tomorrowMorning" | "mondayMorning";

/** The one-click times offered next to the calendar. */
export function schedulePresets(now: Date): Record<SchedulePreset, Date> {
  const morning = { hours: 9, minutes: 0 };
  const inOneHour = addHours(now, 1);
  inOneHour.setSeconds(0, 0);
  return {
    inOneHour,
    tomorrowMorning: atClock(addDays(now, 1), morning),
    mondayMorning: atClock(nextMonday(now), morning),
  };
}

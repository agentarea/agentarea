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

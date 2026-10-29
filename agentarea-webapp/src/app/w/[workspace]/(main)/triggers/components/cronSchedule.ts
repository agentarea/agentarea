/** A clock time a schedule fires at. */
export type CronTime = { hour: number; minute: number };

/**
 * What a cron expression means, in the shapes the Automation listing names
 * in words; anything else is `raw`, shown as the expression itself. Words are
 * the caller's: English in `describeCronExpression`, translated elsewhere.
 */
export type CronSchedule =
  | { kind: "none" }
  | { kind: "everyMinute" }
  | { kind: "everyMinutes"; n: number }
  | { kind: "everyHour" }
  | { kind: "everyHourAt"; minute: number }
  | { kind: "everyHours"; n: number }
  | { kind: "weekdays"; time: CronTime }
  | { kind: "weekends"; time: CronTime }
  | { kind: "weekly"; day: number; time: CronTime }
  | { kind: "daily"; time: CronTime }
  | { kind: "monthly"; day: number; time: CronTime }
  | { kind: "raw"; expr: string };

const NUMBER = /^\d+$/;

/** Read a 5- or 6-field cron expression; the seconds field is ignored. */
export function parseCronSchedule(expr?: string | null): CronSchedule {
  if (!expr) return { kind: "none" };
  let parts = expr.trim().split(/\s+/);
  if (parts.length === 6) parts = parts.slice(1);
  if (parts.length !== 5) return { kind: "raw", expr };

  const [min, hour, dom, month, dow] = parts;
  // None of the named shapes holds for a schedule kept to some months.
  if (month !== "*") return { kind: "raw", expr };

  if (min.startsWith("*/") && hour === "*" && dom === "*" && dow === "*") {
    const n = parseInt(min.slice(2), 10);
    return n === 1 ? { kind: "everyMinute" } : { kind: "everyMinutes", n };
  }
  if (min === "*" && hour === "*" && dom === "*" && dow === "*") {
    return { kind: "everyMinute" };
  }

  if (hour === "*" && dom === "*" && dow === "*" && NUMBER.test(min)) {
    const minute = parseInt(min, 10);
    return minute === 0
      ? { kind: "everyHour" }
      : { kind: "everyHourAt", minute };
  }
  if (hour.startsWith("*/") && dom === "*" && dow === "*") {
    return { kind: "everyHours", n: parseInt(hour.slice(2), 10) };
  }

  if (!NUMBER.test(min) || !NUMBER.test(hour)) return { kind: "raw", expr };
  const time = { hour: parseInt(hour, 10), minute: parseInt(min, 10) };

  if (dom === "*") {
    if (dow === "1-5") return { kind: "weekdays", time };
    if (dow === "0,6" || dow === "6,0" || dow === "0,6,") {
      return { kind: "weekends", time };
    }
    if (/^[0-6]$/.test(dow)) {
      return { kind: "weekly", day: parseInt(dow, 10), time };
    }
    if (dow === "*") return { kind: "daily", time };
  }

  if (NUMBER.test(dom) && dow === "*") {
    return { kind: "monthly", day: parseInt(dom, 10), time };
  }

  return { kind: "raw", expr };
}

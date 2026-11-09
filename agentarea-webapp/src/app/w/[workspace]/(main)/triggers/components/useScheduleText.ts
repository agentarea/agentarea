"use client";

import { useFormatter, useTranslations } from "next-intl";
import { parseCronSchedule, type CronTime } from "./cronSchedule";

/**
 * When a cron schedule fires, in the active language: "Weekdays at 9:00 AM",
 * "По будням в 09:00". An expression it cannot name is shown as it is.
 */
export function useScheduleText() {
  const t = useTranslations("TriggersPage.schedule");
  const format = useFormatter();
  // A clock reading, not an instant: formatted in UTC so no zone shifts it.
  const clock = ({ hour, minute }: CronTime) =>
    format.dateTime(new Date(Date.UTC(2000, 0, 1, hour, minute)), {
      hour: "numeric",
      minute: "2-digit",
      timeZone: "UTC",
    });

  return (expr?: string | null): string => {
    const schedule = parseCronSchedule(expr);
    switch (schedule.kind) {
      case "none":
        return t("custom");
      case "everyMinute":
        return t("everyMinute");
      case "everyMinutes":
        return t("everyMinutes", { n: schedule.n });
      case "everyHour":
        return t("everyHour");
      case "everyHourAt":
        return t("everyHourAt", {
          minute: String(schedule.minute).padStart(2, "0"),
        });
      case "everyHours":
        return t("everyHours", { n: schedule.n });
      case "weekdays":
        return t("weekdays", { time: clock(schedule.time) });
      case "weekends":
        return t("weekends", { time: clock(schedule.time) });
      case "weekly":
        return t("weekly", {
          day: String(schedule.day),
          time: clock(schedule.time),
        });
      case "daily":
        return t("daily", { time: clock(schedule.time) });
      case "monthly":
        return t("monthly", { day: schedule.day, time: clock(schedule.time) });
      case "raw":
        return schedule.expr;
    }
  };
}

"use client";

import { useLocale, useTranslations } from "next-intl";
import { CalendarClock } from "lucide-react";

export function ScheduledRunNotice({ at }: { at: string }) {
  const t = useTranslations("TasksPage");
  const locale = useLocale();
  const when = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(at));

  return (
    <div className="mx-auto mt-4 flex w-full max-w-3xl items-center gap-2.5 rounded-lg border border-border px-4 py-3 text-sm">
      <CalendarClock
        aria-hidden
        className="h-4 w-4 shrink-0 text-muted-foreground"
      />
      <span>{t("scheduledRunNotice", { when })}</span>
    </div>
  );
}

"use client";

import { useFormatter, useNow } from "next-intl";
import { Calendar, Clock } from "lucide-react";

const WEEK = 7 * 24 * 60 * 60 * 1000;

interface TableDateDisplayProps {
  dateString: string;
  oneRow?: boolean;
  onlyDate?: boolean;
  /** Within the last week, say how long ago ("4 days ago") instead of the date. */
  relative?: boolean;
}

/** A table cell's date and time, with icons, in the UI locale. */
export function TableDateDisplay({
  dateString,
  oneRow,
  onlyDate,
  relative,
}: TableDateDisplayProps) {
  const format = useFormatter();
  const now = useNow({ updateInterval: relative ? 60_000 : undefined });
  if (!dateString) return "-";

  const date = new Date(dateString);

  if (relative && now.getTime() - date.getTime() < WEEK) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Clock className="h-3 w-3 shrink-0" />
        {/* Server and browser count from slightly different moments; the
            browser's count replaces it on the next tick. */}
        <time
          suppressHydrationWarning
          dateTime={dateString}
          title={format.dateTime(date, {
            dateStyle: "medium",
            timeStyle: "short",
          })}
          className="whitespace-nowrap"
        >
          {format.relativeTime(date, now)}
        </time>
      </div>
    );
  }

  const day = (
    <div className="flex shrink-0 items-center gap-1.5">
      <Calendar className="h-3 w-3 shrink-0" />
      <span className="whitespace-nowrap">
        {format.dateTime(date, {
          day: "numeric",
          month: "short",
          year: "numeric",
        })}
      </span>
    </div>
  );
  const time = (
    <div className="flex shrink-0 items-center gap-1.5">
      <Clock className="h-3 w-3 shrink-0" />
      <span className="whitespace-nowrap">
        {format.dateTime(date, { hour: "2-digit", minute: "2-digit" })}
      </span>
    </div>
  );

  if (onlyDate) {
    return <div className="text-xs text-muted-foreground">{day}</div>;
  }

  return (
    <div
      className={
        oneRow
          ? "flex items-center gap-3 whitespace-nowrap text-xs text-muted-foreground"
          : "flex flex-col gap-1 text-xs text-muted-foreground"
      }
    >
      {day}
      {time}
    </div>
  );
}

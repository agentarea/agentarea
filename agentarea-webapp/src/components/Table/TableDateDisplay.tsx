"use client";

import { Calendar, Clock } from "lucide-react";

interface TableDateDisplayProps {
  dateString: string;
  oneRow?: boolean;
}

export function TableDateDisplay({
  dateString,
  oneRow,
}: TableDateDisplayProps) {
  if (!dateString) return "-";

  const date = new Date(dateString);

  if (oneRow) {
    return (
      <div className="flex items-center gap-3 text-xs text-muted-foreground whitespace-nowrap">
        <div className="flex items-center gap-1.5 shrink-0">
          <Calendar className="h-3 w-3 shrink-0" />
          <span>
            {date.toLocaleDateString("en", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <Clock className="h-3 w-3 shrink-0" />
          <span>
            {date.toLocaleTimeString("ru-RU", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5 shrink-0">
        <Calendar className="h-3 w-3 shrink-0" />
        <span className="whitespace-nowrap">
          {date.toLocaleDateString("en", {
            day: "numeric",
            month: "short",
            year: "numeric",
          })}
        </span>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <Clock className="h-3 w-3 shrink-0" />
        <span className="whitespace-nowrap">
          {date.toLocaleTimeString("ru-RU", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}

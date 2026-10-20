"use client";

import { useId, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { CalendarClock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import {
  earliestScheduleTime,
  fromLocalInputValue,
  toLocalInputValue,
} from "../utils/scheduleTime";

interface ScheduleChipProps {
  /** Null runs the task as soon as it is sent. */
  value: Date | null;
  onChange: (value: Date | null) => void;
  disabled?: boolean;
}

export function ScheduleChip({ value, onChange, disabled }: ScheduleChipProps) {
  const t = useTranslations("Chat.inputControls");
  const locale = useLocale();
  const inputId = useId();
  const [open, setOpen] = useState(false);

  const label = value
    ? new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(value)
    : t("runNow");

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`${t("when")}: ${label}`}
          className={cn(
            "flex h-7 min-w-0 items-center gap-1 rounded-md px-1.5 text-[13px] leading-[1.2] transition-colors duration-150",
            "hover:bg-zinc-100/70 data-[state=open]:bg-zinc-100/80 dark:hover:bg-zinc-800/80 dark:data-[state=open]:bg-zinc-800/80",
            value
              ? "font-medium text-foreground"
              : "text-zinc-400 dark:text-zinc-300"
          )}
        >
          <CalendarClock
            aria-hidden
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              value ? "text-foreground" : "text-zinc-400 dark:text-zinc-500"
            )}
          />
          <span className="truncate whitespace-nowrap pb-px">{label}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-3">
        <div className="flex flex-col gap-2">
          <label
            htmlFor={inputId}
            className="text-xs font-medium text-muted-foreground"
          >
            {t("runAt")}
          </label>
          <Input
            id={inputId}
            type="datetime-local"
            min={toLocalInputValue(earliestScheduleTime(new Date()))}
            value={value ? toLocalInputValue(value) : ""}
            onChange={(event) =>
              onChange(fromLocalInputValue(event.target.value))
            }
          />
          <div className="flex justify-end gap-2 pt-1">
            {value ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  onChange(null);
                  setOpen(false);
                }}
              >
                {t("runNowAction")}
              </Button>
            ) : null}
            <Button type="button" size="sm" onClick={() => setOpen(false)}>
              {t("done")}
            </Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}

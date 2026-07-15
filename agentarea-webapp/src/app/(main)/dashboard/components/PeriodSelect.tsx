"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Calendar, Check, ChevronsUpDown } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

type Preset = { id: string; labelKey: string; days: number | "mtd" };

const PRESETS: Preset[] = [
  { id: "7d", labelKey: "periodLast7", days: 7 },
  { id: "30d", labelKey: "periodLast30", days: 30 },
  { id: "mtd", labelKey: "periodMonthToDate", days: "mtd" },
  { id: "90d", labelKey: "periodLast90", days: 90 },
];

function rangeLabel(preset: Preset, locale: string): string {
  const fmt = (d: Date) =>
    d.toLocaleDateString(locale, { month: "short", day: "numeric" });
  const end = new Date();
  const start = new Date(end);
  if (preset.days === "mtd") {
    start.setDate(1);
  } else {
    start.setDate(end.getDate() - (preset.days - 1));
  }
  return `${fmt(start)} – ${fmt(end)}`;
}

/**
 * Date-range selector shown in the Dashboard header. Presentational for now —
 * it reflects the chosen preset; wiring it to refetch scoped data is a
 * follow-up once the dashboard endpoint accepts a period parameter.
 */
export function PeriodSelect() {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  const [active, setActive] = useState<Preset>(PRESETS[1]);
  // The range label depends on the current date and locale, so it can't be
  // computed during SSR without risking a hydration mismatch. Show the stable
  // preset name first, then swap in the concrete range after mount.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const label = mounted ? rangeLabel(active, locale) : t(active.labelKey);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex h-[30px] items-center gap-[7px] rounded-[7px] border border-border bg-background px-[11px]",
          "text-[12.5px] font-medium text-foreground/80 transition-colors hover:bg-muted",
          "data-[state=open]:bg-muted"
        )}
      >
        <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="tabular-nums">{label}</span>
        <ChevronsUpDown className="h-3.5 w-3.5 text-muted-foreground/70" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[220px]">
        <DropdownMenuLabel className="text-[10.5px] uppercase tracking-wide text-muted-foreground">
          {t("period")}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {PRESETS.map((p) => (
          <DropdownMenuItem
            key={p.id}
            onSelect={() => setActive(p)}
            className="flex items-center gap-2 text-[13px]"
          >
            <span className="flex-1">{t(p.labelKey)}</span>
            <span className="font-mono text-[11px] text-muted-foreground">
              {mounted ? rangeLabel(p, locale) : ""}
            </span>
            <Check
              className={cn(
                "h-3.5 w-3.5 text-primary",
                active.id === p.id ? "opacity-100" : "opacity-0"
              )}
            />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

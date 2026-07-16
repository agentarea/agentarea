"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { CalendarRange, ChevronDown } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { MenuRow, MenuSectionLabel } from "@/components/ui/menu-row";
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
 * Date-range selector shown in the Dashboard header. Reuses the Skills
 * "Display" popover menu pattern ({@link MenuRow} / {@link MenuSectionLabel}).
 * Presentational for now — it reflects the chosen preset; wiring it to refetch
 * scoped data is a follow-up once the dashboard endpoint accepts a period.
 */
export function PeriodSelect() {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState<Preset>(PRESETS[1]);
  // The range label depends on the current date and locale, so it can't be
  // computed during SSR without risking a hydration mismatch. Show the stable
  // preset name first, then swap in the concrete range after mount.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const label = mounted ? rangeLabel(active, locale) : t(active.labelKey);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn(
          "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] font-normal transition-colors",
          "text-foreground/80 hover:bg-muted/60",
          "data-[state=open]:bg-muted data-[state=open]:text-foreground"
        )}
      >
        <CalendarRange className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="tabular-nums">{label}</span>
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[288px] p-1.5">
        <MenuSectionLabel>{t("period")}</MenuSectionLabel>
        {PRESETS.map((p) => (
          <MenuRow
            key={p.id}
            label={<span className="whitespace-nowrap">{t(p.labelKey)}</span>}
            selected={active.id === p.id}
            onClick={() => {
              setActive(p);
              setOpen(false);
            }}
            trailing={
              <span className="whitespace-nowrap font-mono text-[11px] text-muted-foreground">
                {mounted ? rangeLabel(p, locale) : ""}
              </span>
            }
          />
        ))}
      </PopoverContent>
    </Popover>
  );
}

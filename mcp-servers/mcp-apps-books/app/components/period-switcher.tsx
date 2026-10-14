import type { PeriodKind } from "@shared/books";
import { resolvePeriod, shiftPeriod, type Period } from "@shared/period";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@kit/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@kit/ui/tabs";

const KINDS: [Exclude<PeriodKind, "custom">, string][] = [
  ["month", "Month"],
  ["quarter", "Quarter"],
  ["year", "Year"],
];

export function PeriodSwitcher({
  period,
  today,
  onChange,
  disabled,
}: {
  period: Period;
  today: string;
  onChange: (next: Period) => void;
  disabled?: boolean;
}) {
  // Switching granularity keeps today in view when the current period holds it.
  const anchor = today >= period.from && today <= period.to ? today : period.to;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tabs
        value={period.kind === "custom" ? "" : period.kind}
        onValueChange={(kind) => onChange(resolvePeriod(kind as PeriodKind, anchor))}
      >
        <TabsList aria-label="Period length">
          {KINDS.map(([kind, label]) => (
            <TabsTrigger key={kind} value={kind} disabled={disabled}>
              {label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="bg-background flex h-8 items-center rounded-md border shadow-xs">
        <Button
          variant="ghost"
          size="xs"
          className="h-full rounded-r-none"
          aria-label="Previous period"
          disabled={disabled}
          onClick={() => onChange(shiftPeriod(period, -1))}
        >
          <ChevronLeft />
        </Button>
        <span className="tabular min-w-[92px] px-1 text-center text-xs font-medium">{period.label}</span>
        <Button
          variant="ghost"
          size="xs"
          className="h-full rounded-l-none"
          aria-label="Next period"
          disabled={disabled}
          onClick={() => onChange(shiftPeriod(period, 1))}
        >
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}

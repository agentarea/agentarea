import type { FunnelStage } from "@shared/outreach";
import type { FunnelStageRow } from "@shared/schema";
import { Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Stages before "Contacted" have no people yet, so they cannot filter the people table. */
const FILTERABLE: Record<FunnelStage, boolean> = {
  signals: false,
  qualified: false,
  contacted: true,
  opened: true,
  replied: true,
  positive: true,
  meeting: true,
};

export function FunnelCard({
  funnel,
  selected,
  onSelect,
  className,
}: {
  funnel: FunnelStageRow[];
  selected: FunnelStage | null;
  onSelect: (stage: FunnelStage | null) => void;
  className?: string;
}) {
  const max = Math.max(1, ...funnel.map((stage) => stage.count));
  const overall = funnel[0].count === 0 ? 0 : funnel[funnel.length - 1].count / funnel[0].count;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Funnel</CardTitle>
        <CardDescription>
          Signals detected in the period, followed forward · {formatPercent(overall)} signal → meeting
        </CardDescription>
        <CardAction>
          {selected ? (
            <Button variant="ghost" size="xs" onClick={() => onSelect(null)} className="text-muted-foreground">
              <X /> Clear filter
            </Button>
          ) : (
            <span className="text-subtle-foreground flex items-center gap-1 text-[11px]">
              <Filter className="size-3" /> Click a stage to filter people
            </span>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        {funnel.map((stage, index) => {
          const filterable = FILTERABLE[stage.key];
          const active = selected === stage.key;
          const dimmed = selected !== null && !active;
          // Deeper stages get a stronger fill, so the eye lands on the outcome.
          const strength = 38 + Math.round((index / (funnel.length - 1)) * 62);
          return (
            <button
              key={stage.key}
              type="button"
              disabled={!filterable}
              aria-pressed={active}
              onClick={() => onSelect(active ? null : stage.key)}
              className={cn(
                "group grid grid-cols-[76px_1fr_48px_52px] items-center gap-3 rounded-md px-1.5 py-1 text-left transition-colors",
                filterable ? "hover:bg-accent/70 cursor-pointer" : "cursor-default",
                active && "bg-accent",
                dimmed && "opacity-45",
              )}
            >
              <span className="text-muted-foreground truncate text-xs font-medium group-aria-pressed:text-foreground">
                {stage.label}
              </span>
              <span className="bg-muted relative h-6 overflow-hidden rounded-[5px]">
                <span
                  className="absolute inset-y-0 left-0 rounded-[5px] transition-[width] duration-500 ease-out"
                  style={{
                    width: `${Math.max((stage.count / max) * 100, stage.count > 0 ? 1.5 : 0)}%`,
                    background: `color-mix(in oklab, var(--info) ${strength}%, var(--muted))`,
                  }}
                />
              </span>
              <span className="tabular text-right text-sm font-semibold">{formatNumber(stage.count)}</span>
              <span
                className={cn(
                  "tabular text-right text-[11px]",
                  stage.conversion === null ? "text-subtle-foreground" : "text-muted-foreground",
                )}
              >
                {stage.conversion === null ? "—" : formatPercent(stage.conversion, 0)}
              </span>
            </button>
          );
        })}
        <div className="text-subtle-foreground mt-1 grid grid-cols-[76px_1fr_48px_52px] gap-3 px-1.5 text-[10px] tracking-wide uppercase">
          <span />
          <span />
          <span className="text-right">Count</span>
          <span className="text-right">Step</span>
        </div>
      </CardContent>
    </Card>
  );
}

import { DollarSign, IterationCcw } from "lucide-react";
import Section from "./Section";

interface BudgetInfoProps {
  totalCost: number;
  budgetLimit: number | null;
  iterationsUsed: number;
  maxIterations: number | null;
}

export default function BudgetInfo({
  totalCost,
  budgetLimit,
  iterationsUsed,
  maxIterations,
}: BudgetInfoProps) {
  const costPct =
    budgetLimit && budgetLimit > 0
      ? Math.min((totalCost / budgetLimit) * 100, 100)
      : null;

  const iterPct =
    maxIterations && maxIterations > 0
      ? Math.min((iterationsUsed / maxIterations) * 100, 100)
      : null;

  return (
    <Section title="Budget" contentClassName="text-xs space-y-3">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <DollarSign className="h-3 w-3 text-primary" />
            Cost
          </div>
          <span className="text-sm font-semibold text-foreground">
            ${totalCost.toFixed(4)}
            {budgetLimit != null && (
              <span className="text-muted-foreground font-normal">
                {" "}/ ${budgetLimit.toFixed(2)}
              </span>
            )}
          </span>
        </div>
        {costPct != null && (
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                costPct > 90 ? "bg-destructive" : costPct > 70 ? "bg-yellow-500" : "bg-primary"
              }`}
              style={{ width: `${costPct}%` }}
            />
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <IterationCcw className="h-3 w-3 text-primary" />
            Iterations
          </div>
          <span className="text-sm font-semibold text-foreground">
            {iterationsUsed}
            {maxIterations != null && (
              <span className="text-muted-foreground font-normal">
                {" "}/ {maxIterations}
              </span>
            )}
          </span>
        </div>
        {iterPct != null && (
          <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                iterPct > 90 ? "bg-destructive" : iterPct > 70 ? "bg-yellow-500" : "bg-primary"
              }`}
              style={{ width: `${iterPct}%` }}
            />
          </div>
        )}
      </div>
    </Section>
  );
}

"use client";

import { useLocale } from "next-intl";
import { useCurrency } from "@/hooks/useCurrency";
import { formatMoney } from "@/lib/money";

interface BudgetBarProps {
  label: string;
  used: number;
  total: number;
  currency: string;
  locale: string;
}

function BudgetBar({ label, used, total, currency, locale }: BudgetBarProps) {
  const percentage = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const remaining = Math.max(0, total - used);

  let colorClass = "bg-primary";
  if (percentage >= 100) colorClass = "bg-destructive";
  else if (percentage >= 80) colorClass = "bg-amber-500";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono">
          {formatMoney(used, currency, locale)} /{" "}
          {formatMoney(total, currency, locale)}
        </span>
      </div>
      <div className="relative h-2 w-full overflow-hidden rounded-full bg-secondary">
        <div
          className={`h-full rounded-full transition-all ${colorClass}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{percentage.toFixed(0)}% used</span>
        <span>{formatMoney(remaining, currency, locale)} remaining</span>
      </div>
    </div>
  );
}

interface SplitBudgetDisplayProps {
  inferenceBudget?: number;
  inferenceCost?: number;
  serviceBudget?: number;
  serviceCost?: number;
}

export function SplitBudgetDisplay({
  inferenceBudget,
  inferenceCost = 0,
  serviceBudget,
  serviceCost = 0,
}: SplitBudgetDisplayProps) {
  const locale = useLocale();
  const { currency } = useCurrency();

  return (
    <div className="space-y-3">
      {inferenceBudget != null && inferenceBudget > 0 && (
        <BudgetBar
          label="Inference Budget"
          used={inferenceCost}
          total={inferenceBudget}
          currency={currency}
          locale={locale}
        />
      )}
      {serviceBudget != null && serviceBudget > 0 && (
        <BudgetBar
          label="Service Budget"
          used={serviceCost}
          total={serviceBudget}
          currency={currency}
          locale={locale}
        />
      )}
    </div>
  );
}

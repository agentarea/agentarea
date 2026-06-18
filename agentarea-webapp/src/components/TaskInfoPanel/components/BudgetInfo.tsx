import { useTranslations } from "next-intl";
import { DollarSign } from "lucide-react";
import Section from "./Section";

interface BudgetInfoProps {
  totalCost: number;
  budgetLimit: number | null;
}

export default function BudgetInfo({ totalCost, budgetLimit }: BudgetInfoProps) {
  const t = useTranslations("TaskInfoPanel");

  const costPct =
    budgetLimit && budgetLimit > 0
      ? Math.min((totalCost / budgetLimit) * 100, 100)
      : null;

  return (
    <Section title={t("budget")} contentClassName="text-xs space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          <DollarSign className="h-3 w-3 text-primary" />
          {t("cost")}
        </div>
        <span className="text-sm font-semibold text-foreground">
          ${totalCost.toFixed(4)}
          {budgetLimit != null && (
            <span className="font-normal text-muted-foreground">
              {" "}/ ${budgetLimit.toFixed(2)}
            </span>
          )}
        </span>
      </div>
      {costPct != null && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full transition-all ${
              costPct > 90
                ? "bg-destructive"
                : costPct > 70
                  ? "bg-yellow-500"
                  : "bg-primary"
            }`}
            style={{ width: `${costPct}%` }}
          />
        </div>
      )}
    </Section>
  );
}

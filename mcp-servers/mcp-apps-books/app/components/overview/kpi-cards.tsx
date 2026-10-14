import { Chip } from "@kit/components/chip";
import { Stat, StatGroup } from "@kit/components/stat";
import type { Overview } from "@shared/schema";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { change, dayMonth, wholeMoney } from "@/lib/format";

function Delta({
  value,
  previous,
  good,
  label,
}: {
  value: number;
  previous: number;
  good: "up" | "down";
  label: string;
}) {
  const pct = change(value, previous);
  const direction = pct === null || pct > 0.5 ? "up" : pct < -0.5 ? "down" : "flat";
  const Icon = direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  return (
    <Chip
      tone={direction === "flat" ? "neutral" : direction === good ? "success" : "danger"}
      className="tabular"
      title={label}
    >
      <Icon />
      {pct === null ? "new" : `${pct > 0 ? "+" : ""}${Math.abs(pct) >= 10 ? pct.toFixed(0) : pct.toFixed(1)}%`}
    </Chip>
  );
}

export function KpiCards({ overview }: { overview: Overview }) {
  const { kpis, previous, book, today } = overview;
  const m = (minor: number) => wholeMoney(minor, book.baseCurrency, book.locale);
  const delta = (value: number, before: number, good: "up" | "down") => (
    <Delta value={value} previous={before} good={good} label={`${previous.label}: ${m(before)}`} />
  );
  return (
    <StatGroup label="Key figures" className="md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-6">
      <Stat
        label="Cash on hand"
        value={m(kpis.cash)}
        note={`${overview.accounts.length} accounts · ${dayMonth(kpis.cashAsOf, today)}`}
      />
      <Stat
        label="Income"
        value={m(kpis.income)}
        badge={delta(kpis.income, previous.income, "up")}
        note={`${previous.label}: ${m(previous.income)}`}
      />
      <Stat
        label="Expenses"
        value={m(kpis.expenses)}
        badge={delta(kpis.expenses, previous.expenses, "down")}
        note={`${previous.label}: ${m(previous.expenses)}`}
      />
      <Stat
        label="Net profit"
        value={m(kpis.net)}
        tone={kpis.net < 0 ? "danger" : undefined}
        badge={delta(kpis.net, previous.net, "up")}
        note={`${previous.label}: ${m(previous.net)}`}
      />
      <Stat label="Receivables" value={m(kpis.receivables)} note={`${kpis.receivablesCount} open invoices`} />
      <Stat
        label="Overdue"
        value={m(kpis.overdue)}
        tone={kpis.overdue > 0 ? "danger" : undefined}
        note={kpis.overdueCount ? `${kpis.overdueCount} invoices past due` : "Nothing past due"}
      />
    </StatGroup>
  );
}

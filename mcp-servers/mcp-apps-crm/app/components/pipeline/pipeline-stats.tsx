import { Stat, StatGroup } from "@kit/components/stat";
import type { PipelineSnapshot } from "@shared/schema";
import { formatMoneyShort, formatPercent } from "@/lib/format";

export function PipelineStats({ snapshot }: { snapshot: PipelineSnapshot }) {
  const { kpis, baseCurrency: currency } = snapshot;
  const month = new Date(snapshot.now).toLocaleDateString("en-US", { month: "long" });
  const won90 = kpis.winRate === null ? 0 : Math.round(kpis.winRate * kpis.closedLast90);
  return (
    <StatGroup label="Key metrics">
      <Stat
        label="Open pipeline"
        value={formatMoneyShort(kpis.openValue, currency)}
        note={`${kpis.openCount} open ${kpis.openCount === 1 ? "deal" : "deals"}`}
      />
      <Stat
        label="Weighted forecast"
        value={formatMoneyShort(kpis.weightedValue, currency)}
        note="Value × stage probability"
      />
      <Stat
        label="Won this month"
        value={formatMoneyShort(kpis.wonThisMonth, currency)}
        note={`${kpis.wonThisMonthCount} ${kpis.wonThisMonthCount === 1 ? "deal" : "deals"} in ${month}`}
      />
      <Stat
        label="Win rate"
        value={kpis.winRate === null ? "—" : formatPercent(kpis.winRate)}
        note={
          kpis.closedLast90 === 0 ? "Nothing closed in 90 days" : `${won90} of ${kpis.closedLast90} closed · 90 days`
        }
      />
    </StatGroup>
  );
}

import { useTranslations } from "next-intl";
import { Gauge, Info } from "lucide-react";
import { BoardSectionHeader } from "@/components/board";
import { cn } from "@/lib/utils";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function OutlookRow({
  label,
  sub,
  value,
  strong,
  last,
}: {
  label: string;
  sub: string;
  value: string;
  strong?: boolean;
  last?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-baseline justify-between gap-3 py-2.5 sm:gap-4 sm:py-4",
        !last && "border-b border-dashed [border-color:var(--board-line)]"
      )}
    >
      <div>
        <div className="text-[12.5px] font-medium text-foreground/80 sm:text-[13.5px]">
          {label}
        </div>
        <div className="mt-0.5 text-[10.5px] text-muted-foreground sm:text-[11.5px]">
          {sub}
        </div>
      </div>
      <div
        className={cn(
          "text-right text-[16px] font-semibold tracking-[-0.02em] tabular-nums sm:text-[19px]",
          strong ? "text-foreground" : "text-foreground/90"
        )}
      >
        {value}
      </div>
    </div>
  );
}

export function MonthOutlook({
  today,
  projected,
  cap,
  runRateDays,
}: {
  today: number;
  projected: number | null;
  cap: number | null;
  /** Number of days behind the projection run-rate. */
  runRateDays: number;
}) {
  const t = useTranslations("BudgetsPage");

  const projectedPct = cap && cap > 0 && projected != null ? (projected / cap) * 100 : null;

  const hint =
    cap == null
      ? t("hintNoCap")
      : projectedPct == null || projectedPct < 80
        ? t("hintUnderCap")
        : projectedPct < 100
          ? t("hintNearCap")
          : t("hintOverCap");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Gauge />}
        color="hsl(var(--foreground))"
        title={t("monthOutlook")}
        meta={t("currentPeriod")}
        className="gap-2 sm:gap-2.5"
      />

      <div className="mt-2.5 flex flex-col sm:mt-3.5">
        <OutlookRow
          label={t("today")}
          sub={t("todaySub")}
          value={fmt(today)}
        />
        <OutlookRow
          label={t("projectedEom")}
          sub={t("projectedSub", { days: runRateDays })}
          value={projected == null ? t("noProjection") : fmt(projected)}
        />
        <OutlookRow
          label={t("monthlyCap")}
          sub={
            projectedPct == null
              ? t("capNotSet")
              : t("capProjected", { pct: projectedPct.toFixed(1) })
          }
          value={cap == null ? t("capNotSet") : fmt(cap)}
          strong
          last
        />
      </div>

      <div className="note mt-2.5 flex items-center gap-2 p-0 text-left text-[11px] sm:mt-3.5 sm:text-xs">
        <Info className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
        <span className="leading-relaxed">{hint}</span>
      </div>
    </div>
  );
}

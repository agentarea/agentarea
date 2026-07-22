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
        "flex items-baseline justify-between gap-4 py-4",
        !last && "border-b border-dashed [border-color:var(--board-line)]"
      )}
    >
      <div>
        <div className="text-[13.5px] font-medium text-foreground/80">{label}</div>
        <div className="mt-0.5 text-[11.5px] text-muted-foreground">{sub}</div>
      </div>
      <div
        className={cn(
          "text-right text-[19px] font-semibold tracking-[-0.02em] tabular-nums",
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
      />

      <div className="mt-3.5 flex flex-col">
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

      <div className="mt-3.5 flex items-start gap-2 text-[12px] leading-relaxed text-muted-foreground">
        <Info className="mt-px h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
        <span>{hint}</span>
      </div>
    </div>
  );
}

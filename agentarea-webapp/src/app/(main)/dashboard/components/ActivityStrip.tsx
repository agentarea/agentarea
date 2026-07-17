import { useTranslations } from "next-intl";
import { Activity } from "lucide-react";
import { BoardSectionHeader } from "@/components/board";
import { computeDelta, DeltaBadge, Sparkline } from "@/components/charts/Sparkline";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";
import type { DailyTaskCounts } from "@/lib/api-dashboard";

type Props = {
  data: DailyTaskCounts[];
};

const TONES = {
  completed: { tone: "success", color: "var(--status-success)" },
  failed: { tone: "danger", color: "var(--status-danger)" },
  awaiting: { tone: "warning", color: "var(--status-warning)" },
} as const;

export function ActivityStrip({ data }: Props) {
  const t = useTranslations("DashboardPage");
  const completed = data.map((d) => d.completed);
  const failed = data.map((d) => d.failed);
  const awaiting = data.map((d) => d.input_required);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Activity />}
        color="var(--violet)"
        title={t("activity")}
        meta={t("activityMeta")}
      />

      <div className="mt-2.5 flex flex-1 flex-col gap-2 sm:grid sm:grid-cols-3 lg:flex lg:flex-col lg:gap-1.5">
        <StatCard label={t("completed")} tone="completed" values={completed} goodDirection="up" />
        <StatCard label={t("failed")} tone="failed" values={failed} goodDirection="down" bad />
        <StatCard label={t("awaiting")} tone="awaiting" values={awaiting} goodDirection="down" />
      </div>
    </div>
  );
}

function StatCard({
  label,
  tone,
  values,
  goodDirection,
  bad = false,
}: {
  label: string;
  tone: keyof typeof TONES;
  values: number[];
  goodDirection: "up" | "down";
  bad?: boolean;
}) {
  const delta = computeDelta(values, 1);
  const today = values.at(-1) ?? 0;
  const t = TONES[tone];

  return (
    <div
      className={cn(
        "flex overflow-hidden rounded-[9px] border bg-background transition-colors hover:border-muted-foreground/40",
        "flex-row items-center gap-3.5 px-3.5 py-2",
        "sm:flex-col sm:items-stretch sm:gap-0 sm:px-3 sm:pb-0 sm:pt-3",
        "lg:min-h-[46px] lg:flex-1 lg:flex-row lg:items-stretch lg:gap-3.5 lg:py-2"
      )}
    >
      <div className="flex min-w-0 flex-1 flex-row items-baseline gap-3 sm:flex-none sm:flex-col sm:items-start sm:gap-0 lg:min-w-[120px] lg:flex-none lg:justify-center">
        <StatusIndicator
          tone={t.tone}
          size="sm"
          className="text-[11.5px] font-medium"
        >
          {label}
        </StatusIndicator>
        <div
          className={cn(
            "text-[22px] font-semibold leading-none tracking-[-0.025em] tabular-nums sm:mt-0.5",
            bad && "text-red-500 dark:text-red-400"
          )}
        >
          {today}
        </div>
        <DeltaBadge
          pct={delta.pct}
          direction={delta.direction}
          goodDirection={goodDirection}
        />
      </div>

      <div className="hidden min-w-0 sm:-mx-3 sm:mt-2 sm:block sm:h-[26px] lg:relative lg:mx-0 lg:mt-0 lg:-mr-3.5 lg:-my-2 lg:h-auto lg:flex-1 lg:self-stretch">
        <Sparkline
          values={values}
          width={200}
          height={80}
          stroke={t.color}
          fill={t.color}
          strokeWidth={1.8}
          showDot={false}
          className="h-full w-full lg:absolute lg:inset-0"
        />
      </div>
    </div>
  );
}

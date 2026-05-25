import {
  computeDelta,
  DeltaBadge,
  Sparkline,
} from "@/components/charts/Sparkline";
import type { DailyTaskCounts } from "@/lib/api-dashboard";

type Props = {
  data: DailyTaskCounts[];
};

const NEUTRAL_LINE = "hsl(var(--foreground) / 0.55)";

export function ActivityStrip({ data }: Props) {
  const completed = data.map((d) => d.completed);
  const failed = data.map((d) => d.failed);
  const hitl = data.map((d) => d.input_required);

  return (
    <section>
      <header className="flex items-baseline justify-between">
        <h3 className="text-[13px] font-medium text-foreground">Activity</h3>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          Last 14 days · UTC
        </span>
      </header>

      <div className="mt-3 grid grid-cols-3 gap-6">
        <Item label="Completed" values={completed} goodDirection="up" />
        <Item label="Failed" values={failed} goodDirection="down" />
        <Item label="Awaiting" values={hitl} goodDirection="down" />
      </div>
    </section>
  );
}

function Item({
  label,
  values,
  goodDirection,
}: {
  label: string;
  values: number[];
  goodDirection: "up" | "down";
}) {
  const delta = computeDelta(values, 1);
  const today = values.at(-1) ?? 0;
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-1.5">
        <span className="text-xl font-semibold tabular-nums tracking-tight">
          {today}
        </span>
        <DeltaBadge
          pct={delta.pct}
          direction={delta.direction}
          goodDirection={goodDirection}
        />
      </div>
      <Sparkline
        values={values}
        width={160}
        height={24}
        stroke={NEUTRAL_LINE}
        strokeWidth={1.25}
        className="mt-1.5 w-full text-foreground/60"
      />
    </div>
  );
}

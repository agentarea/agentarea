import Link from "next/link";
import { ArrowRight, MessagesSquare } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import {
  computeDelta,
  DeltaBadge,
  Sparkline,
} from "@/components/charts/Sparkline";
import { Button } from "@/components/ui/button";
import { getAgent, listAgentTasks } from "@/lib/api";
import { getAgentOverview } from "@/lib/api-dashboard";
import { cn } from "@/lib/utils";

const fmtUsd = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

const relTime = (iso: string | null | undefined) => {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
};

const STATUS_DOT: Record<string, string> = {
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  running: "bg-blue-500",
  input_required: "bg-amber-500",
};

export async function AgentOverview({ agentId }: { agentId: string }) {
  const [agentRes, overview, tasksRes] = await Promise.all([
    getAgent(agentId).catch(() => ({ data: null, error: "load failed" })),
    getAgentOverview(agentId).catch(() => null),
    listAgentTasks(agentId).catch(() => ({ data: null, error: "load failed" })),
  ]);

  const agent = (agentRes?.data as any) || { id: agentId, name: agentId };
  const tasks = (tasksRes?.data as any[]) || [];
  const recentTasks = tasks.slice(0, 5);

  const spendValues = (overview?.daily_spend ?? []).map((p) => p.usd);
  const completedValues = (overview?.daily_tasks ?? []).map((d) => d.completed);
  const failedValues = (overview?.daily_tasks ?? []).map((d) => d.failed);

  const throughput7d =
    completedValues.slice(-7).reduce((a, b) => a + b, 0) / 7;
  const throughputPrev =
    completedValues.slice(-14, -7).reduce((a, b) => a + b, 0) / 7;
  const throughputDelta = computeDelta(
    [throughputPrev || 0, throughput7d || 0],
    1
  );

  const sumCompleted = completedValues.slice(-7).reduce((a, b) => a + b, 0);
  const sumFailed = failedValues.slice(-7).reduce((a, b) => a + b, 0);
  const reliability =
    sumCompleted + sumFailed > 0
      ? (sumCompleted / (sumCompleted + sumFailed)) * 100
      : 100;
  const sumCompletedPrev = completedValues
    .slice(-14, -7)
    .reduce((a, b) => a + b, 0);
  const sumFailedPrev = failedValues.slice(-14, -7).reduce((a, b) => a + b, 0);
  const reliabilityPrev =
    sumCompletedPrev + sumFailedPrev > 0
      ? (sumCompletedPrev / (sumCompletedPrev + sumFailedPrev)) * 100
      : reliability;
  const reliabilityDelta = computeDelta([reliabilityPrev, reliability], 1);

  const sumSpend = spendValues.slice(-7).reduce((a, b) => a + b, 0);
  const costPerSuccess = sumCompleted > 0 ? sumSpend / sumCompleted : 0;
  const sumSpendPrev = spendValues.slice(-14, -7).reduce((a, b) => a + b, 0);
  const costPerSuccessPrev =
    sumCompletedPrev > 0 ? sumSpendPrev / sumCompletedPrev : 0;
  const costDelta = computeDelta(
    [costPerSuccessPrev || 0, costPerSuccess || 0],
    1
  );

  return (
    <div>
      <header className="flex items-center gap-3 pb-5">
        <AgentAvatar agent={agent} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[18px] font-semibold tracking-tight">
            {agent.name}
          </h1>
          <p className="truncate text-[12px] text-muted-foreground">
            {agent.description || "No description"}
          </p>
        </div>
        <div className="hidden shrink-0 gap-1.5 sm:flex">
          <Link href={`/agents/${agentId}/new-task`}>
            <Button size="sm" className="h-7 gap-1.5 px-2.5 text-[12px]">
              <MessagesSquare className="h-3.5 w-3.5" />
              New task
            </Button>
          </Link>
          <Link href={`/agents/${agentId}/tasks`}>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 gap-1 px-2 text-[12px] text-muted-foreground hover:text-foreground"
            >
              All tasks <ArrowRight className="h-3 w-3" />
            </Button>
          </Link>
          <Link href={`/agents/${agentId}/settings`}>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 gap-1 px-2 text-[12px] text-muted-foreground hover:text-foreground"
            >
              Settings <ArrowRight className="h-3 w-3" />
            </Button>
          </Link>
        </div>
      </header>

      <KpiStrip
        items={[
          {
            label: "Throughput",
            value: throughput7d.toFixed(1),
            unit: "/ day",
            sparkline: completedValues,
            delta: throughputDelta,
            goodDirection: "up",
            stroke: "hsl(var(--chart-2))",
          },
          {
            label: "Reliability",
            value: `${reliability.toFixed(0)}%`,
            unit: "success rate",
            sparkline: completedValues.map((c, i) =>
              c + failedValues[i] > 0
                ? (c / (c + failedValues[i])) * 100
                : 100
            ),
            delta: reliabilityDelta,
            goodDirection: "up",
            stroke: "hsl(var(--chart-3))",
          },
          {
            label: "$ / success",
            value: costPerSuccess > 0 ? fmtUsd(costPerSuccess) : "—",
            unit: "7-day avg",
            sparkline: spendValues,
            delta: costDelta,
            goodDirection: "down",
            stroke: "hsl(var(--accent))",
          },
          {
            label: "Today",
            value: `${overview?.tasks_done_today ?? 0}`,
            unit: `done · ${overview?.tasks_failed_today ?? 0} failed`,
            sparkline: completedValues.slice(-7),
            delta: { pct: null, direction: "flat", delta: null } as any,
            goodDirection: "up",
            stroke: "hsl(var(--chart-1))",
            tone:
              (overview?.tasks_failed_today ?? 0) > 0
                ? "text-red-600 dark:text-red-400"
                : undefined,
          },
        ]}
      />

      <div className="my-6 border-t border-border/50" />

      <section>
        <header className="flex items-baseline justify-between">
          <h3 className="text-[13px] font-medium text-foreground">
            Recent tasks
          </h3>
          <span className="text-[11px] text-muted-foreground tabular-nums">
            Last activity {relTime(overview?.last_activity_at)}
          </span>
        </header>

        {recentTasks.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-muted-foreground">
            No tasks yet.{" "}
            <Link
              href={`/agents/${agentId}/new-task`}
              className="text-foreground underline-offset-2 hover:underline"
            >
              Start one
            </Link>
            .
          </div>
        ) : (
          <ul className="mt-2 -mx-2 divide-y divide-border/50">
            {recentTasks.map((t) => {
              const cost = Number(t.result?.total_cost ?? 0);
              const status = String(t.status ?? "unknown");
              return (
                <li key={t.id}>
                  <Link
                    href={`/tasks/${t.id}`}
                    className="flex items-center gap-3 rounded px-2 py-2.5 transition-colors hover:bg-muted/50"
                  >
                    <span
                      className={cn(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        STATUS_DOT[status] ?? "bg-zinc-400"
                      )}
                    />
                    <span className="w-20 shrink-0 truncate text-[11px] text-muted-foreground">
                      {status.replace("_", " ")}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12px]">
                      {t.description || t.title || t.id}
                    </span>
                    <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                      {cost > 0 ? fmtUsd(cost) : "—"}
                    </span>
                    <span className="shrink-0 tabular-nums text-[11px] text-muted-foreground">
                      {relTime(t.created_at ?? t.started_at)}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}

type KpiItem = {
  label: string;
  value: string;
  unit: string;
  sparkline: number[];
  delta: ReturnType<typeof computeDelta>;
  goodDirection: "up" | "down";
  stroke: string;
  tone?: string;
};

function KpiStrip({ items }: { items: KpiItem[] }) {
  return (
    <section className="grid grid-cols-2 gap-x-8 gap-y-5 lg:grid-cols-4 lg:divide-x lg:divide-border/50">
      {items.map((it, idx) => (
        <div
          key={it.label}
          className={cn(
            "min-w-0",
            idx > 0 && "lg:pl-8"
          )}
        >
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-muted-foreground">
              {it.label}
            </span>
            <DeltaBadge
              pct={it.delta.pct}
              direction={it.delta.direction}
              goodDirection={it.goodDirection}
            />
          </div>
          <div
            className={cn(
              "mt-1 flex items-baseline gap-1.5",
              it.tone
            )}
          >
            <span className="text-[22px] font-semibold leading-none tabular-nums tracking-tight">
              {it.value}
            </span>
            <span className="text-[11px] font-normal text-muted-foreground">
              {it.unit}
            </span>
          </div>
          {it.sparkline.length > 1 && (
            <Sparkline
              values={it.sparkline}
              width={180}
              height={24}
              stroke={it.stroke}
              strokeWidth={1.25}
              className="mt-2 w-full"
            />
          )}
        </div>
      ))}
    </section>
  );
}

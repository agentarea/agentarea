import { createElement } from "react";
import {
  ArrowUpRight,
  Boxes,
  ChevronRight,
  Clock,
  ListChecks,
  Plug,
  Play,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { computeDelta, DeltaBadge } from "@/components/charts/Sparkline";
import {
  agentColorVar,
  getAgentIconComponent,
  resolveAgentIdentity,
} from "@/lib/agent-identity";
import { getAgent, listAgentTasks } from "@/lib/api";
import { getAgentOverview, getWorkspaceSettings } from "@/lib/api-dashboard";
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

const RUNNING_STATUSES = new Set([
  "running",
  "working",
  "submitted",
  "in_progress",
]);

type TaskPill = "done" | "run" | "wait" | "fail";
const taskPill = (status: string): TaskPill => {
  if (status === "completed") return "done";
  if (status === "failed") return "fail";
  if (status === "input_required") return "wait";
  if (RUNNING_STATUSES.has(status)) return "run";
  return "done";
};
const PILL_CLASS: Record<TaskPill, { dot: string; pill: string; label: string }> =
  {
    done: {
      dot: "bg-emerald-500",
      pill: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
      label: "Done",
    },
    run: {
      dot: "bg-blue-500",
      pill: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
      label: "Running",
    },
    wait: {
      dot: "bg-amber-500",
      pill: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
      label: "Waiting",
    },
    fail: {
      dot: "bg-red-500",
      pill: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
      label: "Failed",
    },
  };

export async function AgentOverview({ agentId }: { agentId: string }) {
  const [agentRes, overview, tasksRes, settings] = await Promise.all([
    getAgent(agentId).catch(() => ({ data: null, error: "load failed" })),
    getAgentOverview(agentId).catch(() => null),
    listAgentTasks(agentId).catch(() => ({ data: null, error: "load failed" })),
    getWorkspaceSettings().catch(() => null),
  ]);

  const agent = (agentRes?.data as any) || { id: agentId, name: agentId };
  // Canonical ref for in-page links: keep URLs on the slug when available,
  // regardless of whether the page was opened by slug or id.
  const agentRef = agent.slug || agentId;
  const tasks = (tasksRes?.data as any[]) || [];

  const runningTasks = tasks.filter((t) =>
    RUNNING_STATUSES.has(String(t.status ?? ""))
  );
  const pendingApprovals = tasks.filter(
    (t) => String(t.status ?? "") === "input_required"
  );
  const recentTasks = tasks
    .filter((t) => !RUNNING_STATUSES.has(String(t.status ?? "")))
    .slice(0, 5);

  // --- derived metrics (real data) ---
  const spendValues = (overview?.daily_spend ?? []).map((p) => p.usd);
  const completedValues = (overview?.daily_tasks ?? []).map((d) => d.completed);
  const failedValues = (overview?.daily_tasks ?? []).map((d) => d.failed);

  const throughput7d = completedValues.slice(-7).reduce((a, b) => a + b, 0) / 7;
  const throughputPrev =
    completedValues.slice(-14, -7).reduce((a, b) => a + b, 0) / 7;
  const throughputDelta = computeDelta(
    [throughputPrev || 0, throughput7d || 0],
    1
  );

  const sumCompleted = completedValues.slice(-7).reduce((a, b) => a + b, 0);
  const sumFailed = failedValues.slice(-7).reduce((a, b) => a + b, 0);
  const totalRuns = sumCompleted + sumFailed;
  const reliability = totalRuns > 0 ? (sumCompleted / totalRuns) * 100 : 100;
  const sumCompletedPrev = completedValues
    .slice(-14, -7)
    .reduce((a, b) => a + b, 0);
  const sumFailedPrev = failedValues.slice(-14, -7).reduce((a, b) => a + b, 0);
  const reliabilityPrev =
    sumCompletedPrev + sumFailedPrev > 0
      ? (sumCompletedPrev / (sumCompletedPrev + sumFailedPrev)) * 100
      : reliability;
  const reliabilityDelta = computeDelta([reliabilityPrev, reliability], 1);

  const spend7d = spendValues.slice(-7).reduce((a, b) => a + b, 0);
  const spend7dPrev = spendValues.slice(-14, -7).reduce((a, b) => a + b, 0);
  const spendDelta = computeDelta([spend7dPrev, spend7d], 1);

  const costMtd = overview?.cost_mtd_usd ?? 0;
  const cap = settings?.monthly_cap_usd ?? null;
  const capPct = cap && cap > 0 ? Math.min(100, (costMtd / cap) * 100) : null;
  const capTone =
    capPct == null
      ? "var(--primary)"
      : capPct >= 100
        ? "var(--destructive)"
        : capPct >= 85
          ? "38 92% 50%"
          : "var(--primary)";

  const doneToday = overview?.tasks_done_today ?? 0;
  const failedToday = overview?.tasks_failed_today ?? 0;

  // --- identity / hero meta ---
  const { colorToken, iconKey } = resolveAgentIdentity(agent);
  const HeroIcon = getAgentIconComponent(iconKey);
  const isActive = String(agent.status ?? "").toLowerCase() === "active";

  const modelLabel =
    agent.model_info?.config_name ||
    agent.model_info?.model_display_name ||
    agent.model_id ||
    null;
  const modelSub =
    agent.model_info?.model_display_name &&
    agent.model_info?.model_display_name !== modelLabel
      ? agent.model_info.model_display_name
      : agent.model_info?.provider_name || null;

  const triggers = (overview?.upcoming ?? []).filter(
    (u) => u.kind === "trigger"
  );

  const skills = agent.skills ?? [];
  const mcpConfigs = agent.tools_config?.mcp_server_configs ?? [];
  const openapiConfigs = agent.tools_config?.openapi_configs ?? [];
  const connectionsCount = mcpConfigs.length + openapiConfigs.length;

  return (
    <div className="mx-auto w-full max-w-[1180px]">
      {/* ===== hero ===== */}
      <header className="flex items-start gap-4 pb-5">
        <span
          className="relative flex h-[50px] w-[50px] shrink-0 items-center justify-center overflow-hidden rounded-[13px] text-white [&>svg]:relative [&>svg]:z-10 [&>svg]:h-6 [&>svg]:w-6"
          style={{ background: agentColorVar(colorToken) }}
        >
          {createElement(HeroIcon, { strokeWidth: 1.9 })}
          <span className="bg-hatch-on-color pointer-events-none absolute inset-0" />
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight">
              {agent.name}
            </h1>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11.5px] font-semibold",
                isActive
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                  : "bg-muted text-muted-foreground"
              )}
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  isActive ? "bg-emerald-500" : "bg-muted-foreground"
                )}
              />
              {isActive ? "Active" : agent.status || "Paused"}
            </span>
          </div>

          {agent.description && (
            <p className="mt-1 max-w-[640px] text-[13px] text-muted-foreground">
              {agent.description}
            </p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted-foreground">
            {modelLabel && (
              <HeroMeta>
                <Boxes className="h-3.5 w-3.5" />
                <span className="font-medium text-foreground/80">
                  {modelLabel}
                </span>
              </HeroMeta>
            )}
            {triggers.length > 0 && (
              <>
                <HeroDot />
                <HeroMeta>
                  <Zap className="h-3.5 w-3.5" />
                  {triggers.length}{" "}
                  {triggers.length === 1 ? "trigger" : "triggers"}
                </HeroMeta>
              </>
            )}
            <HeroDot />
            <HeroMeta>
              <Clock className="h-3.5 w-3.5" />
              Last active{" "}
              <span className="font-medium text-foreground/80">
                {relTime(overview?.last_activity_at)}
              </span>
            </HeroMeta>
          </div>
        </div>
      </header>

      {/* ===== stat strip ===== */}
      <section className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          icon={<Shield />}
          label="Reliability"
          value={`${reliability.toFixed(0)}`}
          unit="% success"
          delta={{
            pct: reliabilityDelta.pct,
            direction: reliabilityDelta.direction,
            goodDirection: "up",
          }}
          sub={
            totalRuns > 0
              ? `${sumCompleted} of ${totalRuns} tasks · 7d`
              : "No runs in the last 7 days"
          }
        />
        <StatCard
          icon={<ListChecks />}
          label="Throughput"
          value={throughput7d.toFixed(1)}
          unit="/ day"
          delta={{
            pct: throughputDelta.pct,
            direction: throughputDelta.direction,
            goodDirection: "up",
          }}
          sub="tasks completed · 7d avg"
        />
        <StatCard
          icon={<Clock />}
          label="Spend · month"
          value={fmtUsd(costMtd)}
          delta={{
            pct: spendDelta.pct,
            direction: spendDelta.direction,
            goodDirection: "down",
          }}
          sub={cap ? `of ${fmtUsd(cap)} cap` : "no cap set"}
        />
        <StatCard
          icon={<ListChecks />}
          label="Today"
          value={`${doneToday}`}
          unit={`done · ${failedToday} failed`}
          tone={failedToday > 0 ? "text-red-600 dark:text-red-400" : undefined}
          sub={
            runningTasks.length > 0
              ? `${runningTasks.length} running now`
              : "nothing running"
          }
        />
      </section>

      {/* ===== two-column body ===== */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.7fr_1fr]">
        {/* left */}
        <div className="flex flex-col gap-4">
          <Card>
            <CardHead
              icon={<Play className="h-3.5 w-3.5" />}
              title="In progress"
              badge={
                runningTasks.length > 0
                  ? `${runningTasks.length} running`
                  : undefined
              }
            />
            {runningTasks.length === 0 ? (
              <EmptyRow text="Nothing running right now." />
            ) : (
              runningTasks.map((t) => (
                <TaskRow key={t.id} task={t} running />
              ))
            )}
          </Card>

          <Card>
            <CardHead
              icon={<ListChecks className="h-3.5 w-3.5" />}
              title="Recent tasks"
              link={{ label: "All tasks", href: `/agents/${agentRef}/tasks` }}
            />
            {recentTasks.length === 0 ? (
              <EmptyRow
                text="No tasks yet."
                action={{
                  label: "Start one",
                  href: `/agents/${agentRef}/new-task`,
                }}
              />
            ) : (
              recentTasks.map((t) => <TaskRow key={t.id} task={t} />)
            )}
          </Card>
        </div>

        {/* right rail */}
        <div className="flex flex-col gap-4">
          {/* at a glance */}
          <Card>
            <CardHead
              icon={<Boxes className="h-3.5 w-3.5" />}
              title="At a glance"
              link={{
                label: "Configure",
                href: `/agents/${agentRef}/settings`,
              }}
            />
            <GlanceRow
              href={`/agents/${agentRef}/settings`}
              tile={
                <span
                  className="grid h-7 w-7 place-items-center rounded-lg text-[11px] font-bold text-white"
                  style={{ background: agentColorVar(colorToken) }}
                >
                  {(agent.model_info?.provider_name?.[0] ?? "M").toUpperCase()}
                </span>
              }
              title={modelLabel || "No model set"}
              sub={modelSub || "Model"}
            />
            <GlanceRow
              href={`/agents/${agentRef}/settings`}
              tile={<GlanceTile icon={<Sparkles className="h-3.5 w-3.5" />} />}
              title="Skills"
              sub={
                skills.length > 0
                  ? skills
                      .slice(0, 3)
                      .map((s: any) => s.name)
                      .join(", ") + (skills.length > 3 ? " +" + (skills.length - 3) : "")
                  : "None granted"
              }
              value={skills.length}
            />
            <GlanceRow
              href={`/agents/${agentRef}/settings`}
              tile={<GlanceTile icon={<Plug className="h-3.5 w-3.5" />} />}
              title="Connections"
              sub={
                connectionsCount > 0
                  ? `${mcpConfigs.length} MCP · ${openapiConfigs.length} API`
                  : "None connected"
              }
              value={connectionsCount}
              last
            />
          </Card>

          {/* guardrails */}
          <Card>
            <CardHead
              icon={<Shield className="h-3.5 w-3.5" />}
              title="Guardrails"
              link={{
                label: "Payments",
                href: `/agents/${agentRef}/payments`,
              }}
            />
            <div className="border-b border-border/60 px-[15px] py-3">
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className="text-[12px] font-medium text-foreground/80">
                  Spend this month
                </span>
                <span className="text-[11.5px] text-muted-foreground">
                  <b className="font-semibold text-foreground tabular-nums">
                    {fmtUsd(costMtd)}
                  </b>
                  {cap ? ` / ${fmtUsd(cap)}` : ""}
                </span>
              </div>
              {capPct != null ? (
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <span
                    className="block h-full rounded-full"
                    style={{
                      width: `${capPct}%`,
                      background: `hsl(${capTone})`,
                    }}
                  />
                </div>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  No workspace spend cap configured.
                </p>
              )}
            </div>

            <Link
              href={`/agents/${agentRef}/tasks?status=input_required`}
              className="flex items-center gap-2.5 px-[15px] py-3 transition-colors hover:bg-muted/50"
            >
              <span
                className={cn(
                  "grid h-7 w-7 shrink-0 place-items-center rounded-lg",
                  pendingApprovals.length > 0
                    ? "bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400"
                    : "bg-muted text-muted-foreground"
                )}
              >
                <Clock className="h-3.5 w-3.5" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12.5px] font-medium">
                  Approvals pending
                </div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {pendingApprovals.length > 0
                    ? "Tasks waiting on human input"
                    : "None pending"}
                </div>
              </div>
              {pendingApprovals.length > 0 && (
                <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[11px] font-bold text-white tabular-nums">
                  {pendingApprovals.length}
                </span>
              )}
            </Link>
          </Card>

          <p className="px-1 text-[11px] leading-relaxed text-muted-foreground">
            Skills, connections, budgets and approvals are governed through your
            workspace — this page links into each.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ------------------------- subcomponents ------------------------- */

function HeroMeta({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 [&>svg]:text-muted-foreground/70">
      {children}
    </span>
  );
}
function HeroDot() {
  return <span className="h-[3px] w-[3px] rounded-full bg-muted-foreground/40" />;
}

type StatDelta = {
  pct: number | null;
  direction: "up" | "down" | "flat";
  goodDirection: "up" | "down";
};
type StatCardProps = {
  icon: React.ReactNode;
  label: string;
  value: string;
  unit?: string;
  sub: string;
  tone?: string;
  delta?: StatDelta;
};
function StatCard({ icon, label, value, unit, sub, tone, delta }: StatCardProps) {
  const showDelta = delta && delta.pct != null && delta.direction !== "flat";
  return (
    <div className="flex flex-col rounded-xl border border-border bg-card px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:text-muted-foreground/60">
          {icon}
          {label}
        </span>
        {showDelta && (
          <DeltaBadge
            pct={delta.pct}
            direction={delta.direction}
            goodDirection={delta.goodDirection}
          />
        )}
      </div>
      <div className={cn("mt-2.5 flex items-baseline gap-1.5", tone)}>
        <span className="text-[24px] font-semibold leading-none tracking-tight tabular-nums">
          {value}
        </span>
        {unit && (
          <span className="text-[12px] font-medium text-muted-foreground">
            {unit}
          </span>
        )}
      </div>
      <div className="mt-2 text-[11.5px] text-muted-foreground">{sub}</div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {children}
    </div>
  );
}

function CardHead({
  icon,
  title,
  badge,
  link,
}: {
  icon: React.ReactNode;
  title: string;
  badge?: string;
  link?: { label: string; href: string };
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-border/60 px-[15px] py-2.5">
      <span className="grid h-[23px] w-[23px] place-items-center rounded-md bg-muted text-foreground/70">
        {icon}
      </span>
      <span className="flex-1 text-[13px] font-semibold">{title}</span>
      {badge && (
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[11px] font-semibold text-muted-foreground">
          {badge}
        </span>
      )}
      {link && (
        <Link
          href={link.href}
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-primary hover:underline dark:text-accent-foreground"
        >
          {link.label}
          <ArrowUpRight className="h-3.5 w-3.5" />
        </Link>
      )}
    </div>
  );
}

function TaskRow({ task, running }: { task: any; running?: boolean }) {
  const status = String(task.status ?? "unknown");
  const pill = taskPill(status);
  const meta = PILL_CLASS[pill];
  const cost = Number(task.result?.total_cost ?? 0);
  const when = relTime(task.created_at ?? task.started_at);
  const title = task.description || task.title || task.id;

  return (
    <Link
      href={`/tasks/${task.id}`}
      className="flex items-center gap-3 border-b border-border/60 px-[15px] py-3 transition-colors last:border-b-0 hover:bg-muted/50"
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          meta.dot,
          running && "ring-[3px] ring-blue-500/20"
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium">{title}</div>
        <div className="text-[11px] text-muted-foreground">
          {running ? "Running" : meta.label} · {when}
        </div>
      </div>
      <span
        className={cn(
          "shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-semibold",
          meta.pill
        )}
      >
        {meta.label}
      </span>
      <span className="w-12 shrink-0 text-right font-mono text-[11.5px] text-muted-foreground tabular-nums">
        {cost > 0 ? fmtUsd(cost) : "—"}
      </span>
    </Link>
  );
}

function EmptyRow({
  text,
  action,
}: {
  text: string;
  action?: { label: string; href: string };
}) {
  return (
    <div className="px-[15px] py-7 text-center text-[12px] text-muted-foreground">
      {text}
      {action && (
        <>
          {" "}
          <Link
            href={action.href}
            className="text-foreground underline-offset-2 hover:underline"
          >
            {action.label}
          </Link>
        </>
      )}
    </div>
  );
}

function GlanceTile({ icon }: { icon: React.ReactNode }) {
  return (
    <span className="grid h-7 w-7 place-items-center rounded-lg bg-muted text-foreground/70">
      {icon}
    </span>
  );
}

function GlanceRow({
  href,
  tile,
  title,
  sub,
  value,
  last,
}: {
  href: string;
  tile: React.ReactNode;
  title: string;
  sub: string;
  value?: number;
  last?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 px-[15px] py-3 transition-colors hover:bg-muted/50",
        !last && "border-b border-border/60"
      )}
    >
      {tile}
      <div className="min-w-0 flex-1">
        <div className="text-[12.5px] font-medium">{title}</div>
        <div className="truncate text-[11px] text-muted-foreground">{sub}</div>
      </div>
      <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
        {value != null && (
          <b className="font-mono font-semibold text-foreground/80 tabular-nums">
            {value}
          </b>
        )}
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/60" />
      </span>
    </Link>
  );
}

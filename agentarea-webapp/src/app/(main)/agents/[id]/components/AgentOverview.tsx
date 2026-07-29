import { createElement } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  ChevronRight,
  CircleDollarSign,
  Clock,
  ListChecks,
  Play,
  Plug,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";
import { policyToRule } from "@/app/(main)/policies/components/policy-rules";
import {
  computeDelta,
  DeltaBadge,
  Sparkline,
} from "@/components/charts/Sparkline";
import { ProviderIcon } from "@/components/ui/provider-icon";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  agentColorVar,
  getAgentIconComponent,
  resolveAgentIdentity,
} from "@/lib/agent-identity";
import {
  getAgent,
  listAgentTasks,
  listMCPServerInstances,
  listMCPServers,
  listPolicies,
  type TaskResponse,
} from "@/lib/api";
import { getAgentOverview, getWorkspaceSettings } from "@/lib/api-dashboard";
import { McpInstance, McpServer } from "@/lib/mcp/resolveMcpRef";
import {
  getAgentStatusPresentation,
  getTaskStatusPresentation,
} from "@/lib/status";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agent";
import type { Policy } from "@/types/policies";
import { resolveAgentToolIcons } from "@/utils/agentToolIcons";
import { AgentToolPills } from "../../components/AgentToolIcons";
import { CatalogAgentPreview } from "./CatalogAgentPreview";

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

export async function AgentOverview({ agentId }: { agentId: string }) {
  const agentRes = await getAgent(agentId);
  const agent = agentRes.data as Agent | undefined;
  if (!agent) notFound();

  // Canonical ref for in-page links: keep URLs on the slug when available,
  // regardless of whether the page was opened by slug or id.
  const agentRef = agent.slug || agentId;

  // A read-only catalog agent has no tenant row, tasks, spend or guardrails.
  // Show a preview + "Add to workspace" CTA instead of the operational dashboard.
  if (agent.is_catalog) {
    return <CatalogAgentPreview agent={agent} agentRef={agentRef} />;
  }

  // Use the resolved UUID for endpoints that require it (list_agent_tasks, etc.).
  const realId: string = agent.id;

  const [
    overview,
    tasksRes,
    settings,
    mcpInstancesRes,
    mcpServersRes,
    policiesRes,
  ] = await Promise.all([
    getAgentOverview(realId).catch(() => null),
    listAgentTasks(realId).catch(() => ({ data: null, error: "load failed" })),
    getWorkspaceSettings().catch(() => null),
    listMCPServerInstances().catch(() => ({ data: [] })),
    listMCPServers({ page_size: 100 }).catch(() => ({ data: [] })),
    listPolicies({ subject_type: "agent", subject_id: realId }).catch(() => ({
      data: [],
    })),
  ]);
  const tasks = (tasksRes?.data as TaskResponse[]) || [];

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
  const totalRunsPrev = sumCompletedPrev + sumFailedPrev;
  const failureRate = totalRuns > 0 ? (sumFailed / totalRuns) * 100 : 0;
  const failureRatePrev =
    totalRunsPrev > 0 ? (sumFailedPrev / totalRunsPrev) * 100 : failureRate;
  const failureDelta = computeDelta([failureRatePrev, failureRate], 1);

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
  const agentStatus = getAgentStatusPresentation(agent.status || "inactive");

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
  const providerName = agent.model_info?.provider_name || null;
  const providerIconUrl = agent.model_info?.provider_icon_url || null;

  const triggers = (overview?.upcoming ?? []).filter(
    (u) => u.kind === "trigger"
  );

  const skills = agent.skills ?? [];

  // Resolve the agent's tools into render-ready icon+label chips, using the live
  // MCP registry so refs map to real names/icons (same as the /agents list).
  const mcpServersData = mcpServersRes?.data;
  const mcpServers: McpServer[] = Array.isArray(mcpServersData)
    ? (mcpServersData as McpServer[])
    : ((mcpServersData as { items?: McpServer[] } | null | undefined)?.items ??
      []);
  const mcpInstanceList = (mcpInstancesRes?.data as McpInstance[]) ?? [];
  const toolIcons = resolveAgentToolIcons(agent, mcpInstanceList, mcpServers);

  // Agent-scoped governance rules, decomposed for compact display.
  const policyRules = ((policiesRes?.data as Policy[]) ?? [])
    .filter((p) => p.enabled !== false)
    .map(policyToRule);

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
            <StatusIndicator
              size="sm"
              tone={agentStatus.tone}
              pulse={agentStatus.pulse}
              className="whitespace-nowrap"
            >
              {agentStatus.label}
            </StatusIndicator>
          </div>

          {agent.description && (
            <p className="mt-1 max-w-[640px] text-[13px] text-muted-foreground">
              {agent.description}
            </p>
          )}

          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-muted-foreground">
            {modelLabel && (
              <HeroMeta>
                {providerIconUrl ? (
                  <ProviderIcon
                    iconUrl={providerIconUrl}
                    name={providerName || modelLabel}
                    size="sm"
                  />
                ) : (
                  <Boxes className="h-3.5 w-3.5" />
                )}
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
        <RunOutcomeCard
          completed={sumCompleted}
          failed={sumFailed}
          successRate={reliability}
          delta={{
            pct: failureDelta.pct,
            direction: failureDelta.direction,
            goodDirection: "down",
          }}
        />
        <ThroughputCard
          average={throughput7d}
          completed={sumCompleted}
          values={completedValues}
          delta={{
            pct: throughputDelta.pct,
            direction: throughputDelta.direction,
            goodDirection: "up",
          }}
        />
        <SpendMetricCard
          costMtd={costMtd}
          cap={cap}
          capPct={capPct}
          capTone={capTone}
          values={spendValues}
          delta={{
            pct: spendDelta.pct,
            direction: spendDelta.direction,
            goodDirection: "down",
          }}
        />
        <TodayActivityCard
          done={doneToday}
          failed={failedToday}
          running={runningTasks.length}
        />
      </section>

      {/* ===== two-column body ===== */}
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.7fr_1fr]">
        {/* left */}
        <div className="flex min-w-0 flex-col gap-4">
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
              runningTasks.map((t) => <TaskRow key={t.id} task={t} />)
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
        <div className="flex min-w-0 flex-col gap-4">
          {/* configuration: model · skills · tools */}
          <Card>
            <CardHead
              icon={<Boxes className="h-3.5 w-3.5" />}
              title="Configuration"
              link={{
                label: "Configure",
                href: `/agents/${agentRef}/settings`,
              }}
            />
            <GlanceRow
              href={`/agents/${agentRef}/settings`}
              tile={
                providerIconUrl ? (
                  <span className="grid h-7 w-7 place-items-center rounded-lg bg-muted">
                    <ProviderIcon
                      iconUrl={providerIconUrl}
                      name={providerName || modelLabel || "Model"}
                      size="md"
                    />
                  </span>
                ) : (
                  <span
                    className="grid h-7 w-7 place-items-center rounded-lg text-[11px] font-bold text-white"
                    style={{ background: agentColorVar(colorToken) }}
                  >
                    {(
                      agent.model_info?.provider_name?.[0] ?? "M"
                    ).toUpperCase()}
                  </span>
                )
              }
              title={modelLabel || "No model set"}
              sub={modelSub || "Model"}
            />
            <ConfigSection
              icon={<Sparkles className="h-3.5 w-3.5" />}
              title="Skills"
              count={skills.length}
            >
              {skills.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {skills.map((s) => (
                    <span
                      key={s.id}
                      title={s.description ?? s.name}
                      className="inline-flex min-w-0 items-center rounded-full bg-muted px-2 py-0.5 text-[11.5px] text-foreground/80"
                    >
                      <span className="max-w-[150px] truncate">{s.name}</span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-[11.5px] text-muted-foreground">
                  None granted
                </p>
              )}
            </ConfigSection>
            <ConfigSection
              icon={<Plug className="h-3.5 w-3.5" />}
              title="Tools"
              count={toolIcons.length}
              last
            >
              {toolIcons.length > 0 ? (
                <AgentToolPills tools={toolIcons} />
              ) : (
                <p className="text-[11.5px] text-muted-foreground">
                  None connected
                </p>
              )}
            </ConfigSection>
          </Card>

          {/* policies (agent-scoped governance rules) */}
          {policyRules.length > 0 && (
            <Card>
              <CardHead
                icon={<Shield className="h-3.5 w-3.5" />}
                title="Policies"
                badge={`${policyRules.length}`}
                link={{ label: "Manage", href: "/policies" }}
              />
              <div className="flex flex-col gap-2 px-[15px] py-3">
                {policyRules.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-start justify-between gap-3"
                  >
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium text-foreground/90">
                        {r.label}
                      </div>
                      {r.value && (
                        <div className="truncate text-[11px] text-muted-foreground">
                          {r.value}
                        </div>
                      )}
                    </div>
                    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                      {r.category}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

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
  return (
    <span className="h-[3px] w-[3px] rounded-full bg-muted-foreground/40" />
  );
}

type StatDelta = {
  pct: number | null;
  direction: "up" | "down" | "flat";
  goodDirection: "up" | "down";
};

function MetricCardHeader({
  icon,
  label,
  delta,
  deltaTitle,
}: {
  icon: React.ReactNode;
  label: string;
  delta?: StatDelta;
  deltaTitle?: string;
}) {
  const showDelta = delta && delta.pct != null && delta.direction !== "flat";

  return (
    <div className="flex items-center justify-between gap-2">
      <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:text-muted-foreground/60">
        {icon}
        {label}
      </span>
      {showDelta && (
        <span title={deltaTitle}>
          <DeltaBadge
            pct={delta.pct}
            direction={delta.direction}
            goodDirection={delta.goodDirection}
          />
        </span>
      )}
    </div>
  );
}

function SegmentedBar({
  segments,
  ariaLabel,
  className,
}: {
  segments: { label: string; value: number; className: string }[];
  ariaLabel: string;
  className?: string;
}) {
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={cn(
        "flex h-1.5 overflow-hidden rounded-full bg-muted",
        className
      )}
    >
      {segments.map((segment) => (
        <span
          key={segment.label}
          className={cn("h-full", segment.className)}
          style={{
            width: total > 0 ? `${(segment.value / total) * 100}%` : "0%",
          }}
          title={`${segment.value} ${segment.label}`}
        />
      ))}
    </div>
  );
}

function RunOutcomeCard({
  completed,
  failed,
  successRate,
  delta,
}: {
  completed: number;
  failed: number;
  successRate: number;
  delta: StatDelta;
}) {
  const total = completed + failed;

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card px-4 py-3.5">
      <MetricCardHeader
        icon={<Shield />}
        label="Reliability · 7d"
        delta={delta}
        deltaTitle="Failure rate compared with the previous 7 days"
      />

      {total > 0 ? (
        <>
          <div className="mt-2.5 flex items-baseline justify-between gap-3">
            <div className="flex min-w-0 items-baseline gap-1.5">
              <span
                className={cn(
                  "text-[26px] font-semibold leading-none tracking-tight tabular-nums",
                  failed > 0 && "text-red-600 dark:text-red-400"
                )}
              >
                {failed}
              </span>
              <span className="truncate text-[12px] font-medium text-muted-foreground">
                / {total} failed
              </span>
            </div>
            <span className="shrink-0 text-[11.5px] font-medium text-foreground/80 tabular-nums">
              {successRate.toFixed(0)}% success
            </span>
          </div>

          <SegmentedBar
            ariaLabel={`${completed} completed and ${failed} failed out of ${total} terminal runs in the last 7 days`}
            className="mt-3"
            segments={[
              {
                label: "completed",
                value: completed,
                className: "bg-emerald-500",
              },
              { label: "failed", value: failed, className: "bg-red-500" },
            ]}
          />

          <div className="mt-2 flex items-center justify-between gap-2 text-[11.5px] text-muted-foreground">
            <span>{completed} completed</span>
            <span>{failed} failed</span>
          </div>
        </>
      ) : (
        <>
          <div className="mt-2.5 text-[24px] font-semibold leading-none tracking-tight text-muted-foreground">
            —
          </div>
          <div className="mt-3 h-1.5 rounded-full bg-muted" />
          <div className="mt-2 text-[11.5px] text-muted-foreground">
            No terminal runs in the last 7 days
          </div>
        </>
      )}
    </div>
  );
}

function ThroughputCard({
  average,
  completed,
  values,
  delta,
}: {
  average: number;
  completed: number;
  values: number[];
  delta: StatDelta;
}) {
  const max = Math.max(...values, 1);

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card px-4 py-3.5">
      <MetricCardHeader
        icon={<ListChecks />}
        label="Throughput · 7d"
        delta={delta}
        deltaTitle="Average completed tasks per day compared with the previous 7 days"
      />
      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span className="text-[24px] font-semibold leading-none tracking-tight tabular-nums">
          {average.toFixed(1)}
        </span>
        <span className="text-[12px] font-medium text-muted-foreground">
          / day
        </span>
      </div>

      <div
        role="img"
        aria-label={`Daily completed tasks over 14 days: ${values.join(", ") || "no data"}`}
        className="mt-2.5 flex h-7 items-end gap-1"
      >
        {values.length > 0 ? (
          values.map((value, index) => (
            <span
              key={index}
              className={cn(
                "min-w-0 flex-1 rounded-[2px]",
                index >= Math.max(0, values.length - 7)
                  ? "bg-primary/80"
                  : "bg-primary/20"
              )}
              style={{
                height: value === 0 ? 2 : Math.max(4, (value / max) * 28),
              }}
              title={`Day ${index + 1}: ${value} completed`}
            />
          ))
        ) : (
          <span className="h-0.5 w-full rounded-full bg-muted" />
        )}
      </div>

      <div className="mt-2 text-[11.5px] text-muted-foreground">
        {completed} completed in the last 7 days
      </div>
    </div>
  );
}

function SpendMetricCard({
  costMtd,
  cap,
  capPct,
  capTone,
  values,
  delta,
}: {
  costMtd: number;
  cap: number | null;
  capPct: number | null;
  capTone: string;
  values: number[];
  delta: StatDelta;
}) {
  return (
    <div className="flex flex-col rounded-xl border border-border bg-card px-4 py-3.5">
      <MetricCardHeader
        icon={<CircleDollarSign />}
        label="Spend · month"
        delta={delta}
        deltaTitle="Spend in the last 7 days compared with the previous 7 days"
      />

      <div className="mt-2.5 flex items-end justify-between gap-3">
        <span className="min-w-0 truncate text-[24px] font-semibold leading-none tracking-tight tabular-nums">
          {fmtUsd(costMtd)}
        </span>
        <Sparkline
          values={values}
          width={72}
          height={25}
          stroke="hsl(var(--primary))"
          className="shrink-0 text-primary"
        />
      </div>

      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
        {capPct != null && (
          <div
            className="h-full rounded-full transition-[width]"
            style={{
              width: `${capPct}%`,
              background: `hsl(${capTone})`,
            }}
          />
        )}
      </div>

      <div className="mt-2 flex items-center justify-between gap-2 text-[11.5px] text-muted-foreground">
        <span>{cap ? `of ${fmtUsd(cap)} cap` : "No monthly cap"}</span>
        {capPct != null && <span>{capPct.toFixed(0)}% used</span>}
      </div>
    </div>
  );
}

function TodayActivityCard({
  done,
  running,
  failed,
}: {
  done: number;
  running: number;
  failed: number;
}) {
  const total = done + running + failed;

  return (
    <div className="flex flex-col rounded-xl border border-border bg-card px-4 py-3.5">
      <MetricCardHeader icon={<Activity />} label="Today" />

      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span className="text-[24px] font-semibold leading-none tracking-tight tabular-nums">
          {done}
        </span>
        <span className="text-[12px] font-medium text-muted-foreground">
          completed
        </span>
      </div>

      <SegmentedBar
        ariaLabel={`${done} completed today, ${running} currently running, and ${failed} failed today`}
        className="mt-3"
        segments={[
          { label: "done", value: done, className: "bg-emerald-500" },
          { label: "running", value: running, className: "bg-sky-500" },
          { label: "failed", value: failed, className: "bg-red-500" },
        ]}
      />

      <div className="mt-2 grid grid-cols-3 gap-1 text-[10.5px] text-muted-foreground">
        <span className="truncate">
          <span
            aria-hidden="true"
            className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-emerald-500"
          />
          {done} done
        </span>
        <span className="truncate text-center">
          <span
            aria-hidden="true"
            className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-sky-500"
          />
          {running} running
        </span>
        <span
          className={cn(
            "truncate text-right",
            failed > 0 && "text-red-600 dark:text-red-400"
          )}
        >
          <span
            aria-hidden="true"
            className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-red-500"
          />
          {failed} failed
        </span>
      </div>

      {total === 0 && (
        <span className="sr-only">No task activity recorded today</span>
      )}
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

function TaskRow({ task }: { task: TaskResponse }) {
  const status = String(task.status ?? "unknown");
  const presentation = getTaskStatusPresentation(status);
  const resultCost =
    task.result && typeof task.result === "object"
      ? task.result.total_cost
      : undefined;
  const cost = Number(task.total_cost ?? resultCost ?? 0);
  const when = relTime(task.created_at);
  const title = task.description || task.id;

  return (
    <Link
      href={`/tasks/${task.id}`}
      className="flex items-center gap-3 border-b border-border/60 px-[15px] py-3 transition-colors last:border-b-0 hover:bg-muted/50"
    >
      <StatusIndicator
        size="sm"
        tone={presentation.tone}
        pulse={presentation.pulse}
        className="shrink-0"
      >
        <span className="sr-only">{presentation.label}</span>
      </StatusIndicator>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium">{title}</div>
        <div className="text-[11px] text-muted-foreground">
          {presentation.label} · {when}
        </div>
      </div>
      <StatusIndicator
        size="sm"
        tone={presentation.tone}
        pulse={presentation.pulse}
        className="whitespace-nowrap"
      >
        {presentation.label}
      </StatusIndicator>
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

function ConfigSection({
  icon,
  title,
  count,
  last,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count?: number;
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("px-[15px] py-3", !last && "border-b border-border/60")}>
      <div className="mb-2 flex items-center gap-2.5">
        <GlanceTile icon={icon} />
        <span className="flex-1 text-[12.5px] font-medium">{title}</span>
        {count != null && (
          <b className="font-mono text-[12px] font-semibold text-foreground/80 tabular-nums">
            {count}
          </b>
        )}
      </div>
      {children}
    </div>
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

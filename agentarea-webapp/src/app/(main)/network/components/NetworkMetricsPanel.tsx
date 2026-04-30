"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CircleDot,
  DollarSign,
  GitBranch,
  type LucideIcon,
  Plug,
} from "lucide-react";
import { getAllTasksAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

interface NetworkNodeData {
  id: string;
  type: "agent" | "mcp_instance" | "openapi_connection" | "skill" | "trigger";
  label: string;
  status?: string | null;
  metadata: Record<string, any>;
}

interface NetworkEdgeData {
  id: string;
  source: string;
  target: string;
  relation: string;
}

interface TopologyResponse {
  nodes: NetworkNodeData[];
  edges: NetworkEdgeData[];
}

interface TaskSummary {
  id: string;
  agent_id?: string | null;
  status?: string | null;
  total_cost?: number | string | null;
}

const ACTIVE_STATUSES = new Set([
  "running",
  "in_progress",
  "pending",
  "queued",
  "awaiting_input",
  "awaiting_approval",
  "paused",
]);

const PROBLEM_STATUSES = new Set([
  "failed",
  "error",
  "unhealthy",
  "degraded",
  "inactive",
  "cancelled",
]);

function fmtNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function fmtCost(value: number | null) {
  if (value === null) return "-";
  if (value <= 0) return "$0";
  if (value < 0.01) return "<$0.01";
  return `$${value.toFixed(value < 1 ? 3 : 2)}`;
}

function toNumber(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone?: "neutral" | "good" | "warn" | "blue";
}) {
  return (
    <div className="min-w-[126px] rounded-xl border border-zinc-200 bg-white/95 px-3 py-2 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/90">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-400">
          {label}
        </span>
        <Icon
          className={cn(
            "h-3.5 w-3.5",
            tone === "good" && "text-emerald-500",
            tone === "warn" && "text-amber-500",
            tone === "blue" && "text-blue-500",
            tone === "neutral" && "text-zinc-400"
          )}
        />
      </div>
      <p className="mt-1 text-base font-semibold leading-none text-zinc-950 dark:text-zinc-50">
        {value}
      </p>
      {hint && (
        <p className="mt-1 truncate text-[10px] leading-tight text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

export default function NetworkMetricsPanel({
  topology,
}: {
  topology: TopologyResponse;
}) {
  const [tasks, setTasks] = useState<TaskSummary[] | null>(null);
  const [tasksUnavailable, setTasksUnavailable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTasksUnavailable(false);
    getAllTasksAction()
      .then((res: any) => {
        if (cancelled) return;
        const data = res?.data ?? [];
        setTasks(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (cancelled) return;
        setTasks([]);
        setTasksUnavailable(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = useMemo(() => {
    const agentIds = new Set(
      topology.nodes.filter((n) => n.type === "agent").map((n) => n.id)
    );
    const agentCount = agentIds.size;
    const externalCount = topology.nodes.filter(
      (n) =>
        n.type === "mcp_instance" ||
        n.type === "openapi_connection" ||
        n.type === "skill"
    ).length;
    const triggerCount = topology.nodes.filter((n) => n.type === "trigger").length;
    const problemNodes = topology.nodes.filter((n) =>
      PROBLEM_STATUSES.has(String(n.status ?? "").toLowerCase())
    ).length;

    const knownTasks = (tasks ?? []).filter((task) =>
      task.agent_id ? agentIds.has(String(task.agent_id)) : true
    );
    const activeTasks = knownTasks.filter((task) =>
      ACTIVE_STATUSES.has(String(task.status ?? "").toLowerCase())
    ).length;
    const totalCost = knownTasks.reduce(
      (sum, task) => sum + toNumber(task.total_cost),
      0
    );

    return {
      agentCount,
      externalCount,
      triggerCount,
      problemNodes,
      activeTasks,
      taskCount: knownTasks.length,
      totalCost: tasks === null && !tasksUnavailable ? null : totalCost,
    };
  }, [tasks, tasksUnavailable, topology]);

  const healthHint =
    metrics.problemNodes > 0
      ? `${metrics.problemNodes} need attention`
      : `${metrics.triggerCount} triggers`;

  return (
    <div className="absolute left-4 top-4 z-10 flex max-w-[calc(100%-2rem)] flex-wrap gap-2">
      <MetricTile
        label="Agents"
        value={fmtNumber(metrics.agentCount)}
        hint={healthHint}
        icon={Bot}
        tone={metrics.problemNodes > 0 ? "warn" : "good"}
      />
      <MetricTile
        label="Active tasks"
        value={fmtNumber(metrics.activeTasks)}
        hint={`${fmtNumber(metrics.taskCount)} total tasks`}
        icon={CircleDot}
        tone={metrics.activeTasks > 0 ? "blue" : "neutral"}
      />
      <MetricTile
        label="Spent"
        value={fmtCost(metrics.totalCost)}
        hint={tasks === null && !tasksUnavailable ? "Loading usage..." : "LLM cost"}
        icon={DollarSign}
        tone="neutral"
      />
      <MetricTile
        label="Integrations"
        value={fmtNumber(metrics.externalCount)}
        hint={`${fmtNumber(topology.edges.length)} links`}
        icon={Plug}
        tone="neutral"
      />
      {metrics.problemNodes > 0 && (
        <MetricTile
          label="Attention"
          value={fmtNumber(metrics.problemNodes)}
          hint="Failed or inactive"
          icon={AlertTriangle}
          tone="warn"
        />
      )}
      {tasksUnavailable && (
        <MetricTile
          label="Tasks"
          value="-"
          hint="Usage unavailable"
          icon={GitBranch}
          tone="warn"
        />
      )}
    </div>
  );
}

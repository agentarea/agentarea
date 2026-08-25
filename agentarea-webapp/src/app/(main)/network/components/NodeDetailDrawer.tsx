"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  CircleDot,
  Clock,
  ExternalLink,
  Globe,
  Loader2,
  Plug,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatApiError } from "@/lib/api-errors";
import { listAgentTasksAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import type { NetworkNodeData, TopologyResponse } from "../types";

const TYPE_CONFIG = {
  agent: {
    icon: Bot,
    label: "Agent",
    color: "text-zinc-500",
    href: (id: string) => `/agents/${id}`,
  },
  mcp_instance: {
    icon: Plug,
    label: "MCP server",
    color: "text-emerald-500",
    href: (id: string) => `/connections/${id}`,
  },
  openapi_connection: {
    icon: Globe,
    label: "OpenAPI",
    color: "text-rose-500",
    href: (id: string) => `/connections/openapi/${id}`,
  },
  skill: {
    icon: Sparkles,
    label: "Skill",
    color: "text-sky-500",
    href: (id: string) => `/skills/${id}`,
  },
  trigger: {
    icon: Zap,
    label: "Trigger",
    color: "text-amber-500",
    href: (id: string) => `/triggers/${id}`,
  },
};

interface AgentTask {
  id: string;
  status: string;
  total_cost?: number | null;
  created_at?: string;
  query?: string | null;
  description?: string | null;
}

const RUNNING_STATUSES = new Set([
  "running",
  "in_progress",
  "pending",
  "queued",
  "awaiting_input",
  "awaiting_approval",
  "paused",
]);
const TERMINAL_OK = new Set(["completed", "succeeded", "done"]);
const TERMINAL_BAD = new Set(["failed", "cancelled", "error"]);

function fmtCost(c: number | null | undefined) {
  if (!c || c <= 0) return "—";
  if (c < 0.01) return `<$0.01`;
  return `$${c.toFixed(c < 1 ? 3 : 2)}`;
}

function fmtRelative(iso?: string) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Date.now() - t;
  const m = Math.round(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  return `${d}d ago`;
}

function StatusPill({ status }: { status: string }) {
  const norm = status.toLowerCase();
  const tone = TERMINAL_OK.has(norm)
    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
    : TERMINAL_BAD.has(norm)
      ? "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"
      : RUNNING_STATUSES.has(norm)
        ? "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
        : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider",
        tone
      )}
    >
      {status}
    </span>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <h4 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-zinc-500 dark:text-zinc-400">
          {title}
        </h4>
        {count !== undefined && (
          <span className="text-[10px] text-zinc-400">({count})</span>
        )}
      </div>
      {children}
    </div>
  );
}

function StatTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-zinc-200 bg-zinc-50/40 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900/40">
      <p className="text-[9px] font-semibold uppercase tracking-[0.14em] text-zinc-500 dark:text-zinc-500">
        {label}
      </p>
      <p className="mt-0.5 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
        {value}
      </p>
      {hint && (
        <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

function AgentSections({ agentId }: { agentId: string }) {
  const [tasks, setTasks] = useState<AgentTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTasks(null);
    setError(null);
    listAgentTasksAction(agentId)
      .then((res) => {
        if (cancelled) return;
        const data = res?.data ?? res;
        setTasks(Array.isArray(data) ? data : []);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(formatApiError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const grouped = useMemo(() => {
    if (!tasks) return null;
    const running: AgentTask[] = [];
    const recent: AgentTask[] = [];
    const approvals: AgentTask[] = [];
    let totalCost = 0;
    let succeeded = 0;
    let failed = 0;
    for (const t of tasks) {
      const s = (t.status || "").toLowerCase();
      if (s === "awaiting_approval" || s === "awaiting_input") approvals.push(t);
      if (RUNNING_STATUSES.has(s)) running.push(t);
      else recent.push(t);
      if (TERMINAL_OK.has(s)) succeeded++;
      else if (TERMINAL_BAD.has(s)) failed++;
      totalCost += t.total_cost ?? 0;
    }
    recent.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
    return {
      running,
      recent: recent.slice(0, 8),
      approvals,
      totalCost,
      total: tasks.length,
      succeeded,
      failed,
    };
  }, [tasks]);

  if (error) {
    return (
      <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
        Failed to load tasks: {error}
      </p>
    );
  }

  if (!tasks || !grouped) {
    return (
      <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading task data…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <StatTile label="Tasks" value={grouped.total} />
        <StatTile
          label="Cost"
          value={fmtCost(grouped.totalCost)}
          hint="LLM tokens"
        />
        <StatTile
          label="Success"
          value={`${grouped.succeeded}`}
          hint={grouped.failed ? `${grouped.failed} failed` : undefined}
        />
      </div>

      {grouped.approvals.length > 0 && (
        <Section title="Awaiting approval" count={grouped.approvals.length}>
          <ul className="space-y-1.5">
            {grouped.approvals.map((t) => (
              <li
                key={t.id}
                className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/60 px-2.5 py-1.5 text-xs dark:border-amber-900 dark:bg-amber-950/30"
              >
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600" />
                <span className="min-w-0 flex-1 truncate">
                  {t.query || t.description || t.id}
                </span>
                <Link
                  href={`/agents/${agentId}/tasks/${t.id}`}
                  className="shrink-0 text-[10px] font-medium text-amber-700 hover:underline dark:text-amber-300"
                >
                  Resolve
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {grouped.running.length > 0 && (
        <Section title="Running" count={grouped.running.length}>
          <ul className="space-y-1.5">
            {grouped.running.map((t) => (
              <li
                key={t.id}
                className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50/40 px-2.5 py-1.5 text-xs dark:border-zinc-800 dark:bg-zinc-900/40"
              >
                <CircleDot className="h-3.5 w-3.5 shrink-0 animate-pulse text-blue-500" />
                <span className="min-w-0 flex-1 truncate">
                  {t.query || t.description || t.id}
                </span>
                <StatusPill status={t.status} />
                <Link
                  href={`/agents/${agentId}/tasks/${t.id}`}
                  className="shrink-0 text-muted-foreground hover:text-foreground"
                >
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Recent" count={grouped.recent.length}>
        {grouped.recent.length === 0 ? (
          <p className="px-2.5 text-xs text-muted-foreground">No history yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {grouped.recent.map((t) => {
              const s = (t.status || "").toLowerCase();
              const Icon = TERMINAL_BAD.has(s)
                ? AlertTriangle
                : TERMINAL_OK.has(s)
                  ? CheckCircle2
                  : Clock;
              const tone = TERMINAL_BAD.has(s)
                ? "text-red-500"
                : TERMINAL_OK.has(s)
                  ? "text-emerald-500"
                  : "text-zinc-400";
              return (
                <li
                  key={t.id}
                  className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <Icon className={cn("h-3.5 w-3.5 shrink-0", tone)} />
                  <span className="min-w-0 flex-1 truncate">
                    {t.query || t.description || t.id}
                  </span>
                  <span className="shrink-0 text-[10px] text-muted-foreground">
                    {fmtCost(t.total_cost)} · {fmtRelative(t.created_at)}
                  </span>
                  <Link
                    href={`/agents/${agentId}/tasks/${t.id}`}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
    </div>
  );
}

function ToolConsumerSections({
  toolId,
  topology,
}: {
  toolId: string;
  topology: TopologyResponse;
}) {
  const consumers = useMemo(() => {
    const consumerEdges = topology.edges.filter(
      (e) =>
        e.target === toolId &&
        (e.relation === "uses_mcp" ||
          e.relation === "uses_openapi" ||
          e.relation === "has_skill")
    );
    const byAgent = new Map<string, NetworkNodeData>();
    for (const e of consumerEdges) {
      const agent = topology.nodes.find((n) => n.id === e.source);
      if (agent) byAgent.set(agent.id, agent);
    }
    return Array.from(byAgent.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );
  }, [toolId, topology]);

  return (
    <Section title="Used by agents" count={consumers.length}>
      {consumers.length === 0 ? (
        <p className="px-2.5 text-xs text-muted-foreground">
          No agents reference this resource yet.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {consumers.map((agent) => (
            <li
              key={agent.id}
              className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs dark:border-zinc-800 dark:bg-zinc-900"
            >
              <Bot className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
              <span className="min-w-0 flex-1 truncate">{agent.label}</span>
              <Link
                href={`/agents/${agent.id}`}
                className="shrink-0 text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="h-3 w-3" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function TriggerSections({
  triggerId,
  topology,
}: {
  triggerId: string;
  topology: TopologyResponse;
}) {
  const targetAgent = useMemo(() => {
    const e = topology.edges.find(
      (x) => x.relation === "has_trigger" && x.target === triggerId
    );
    if (!e) return null;
    return topology.nodes.find((n) => n.id === e.source) ?? null;
  }, [triggerId, topology]);

  return (
    <Section title="Routes to">
      {targetAgent ? (
        <Link
          href={`/agents/${targetAgent.id}`}
          className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-white px-2.5 py-1.5 text-xs hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:bg-zinc-800"
        >
          <Bot className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
          <span className="min-w-0 flex-1 truncate">{targetAgent.label}</span>
          <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" />
        </Link>
      ) : (
        <p className="px-2.5 text-xs text-muted-foreground">
          Trigger has no target agent yet.
        </p>
      )}
    </Section>
  );
}

export default function NodeDetailDrawer({
  node,
  topology,
  onClose,
}: {
  node: NetworkNodeData;
  topology: TopologyResponse;
  onClose: () => void;
}) {
  const config = TYPE_CONFIG[node.type];
  const Icon = config.icon;

  return (
    <div className="absolute right-3 top-3 bottom-3 z-20 w-[420px] max-w-[42vw] rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex h-full flex-col">
        <div className="flex items-start gap-3 border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
          <div
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-zinc-100 dark:bg-zinc-900",
              config.color
            )}
          >
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold leading-tight text-zinc-900 dark:text-zinc-100">
              {node.label}
            </p>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-500">
                {config.label}
              </span>
              {node.status && <StatusPill status={node.status} />}
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 -mr-1 shrink-0"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>

        <ScrollArea className="flex-1 px-4 py-3">
          <div className="space-y-5 pb-3">
            {node.type === "agent" && <AgentSections agentId={node.id} />}

            {(node.type === "mcp_instance" ||
              node.type === "openapi_connection" ||
              node.type === "skill") && (
              <ToolConsumerSections toolId={node.id} topology={topology} />
            )}

            {node.type === "trigger" && (
              <TriggerSections triggerId={node.id} topology={topology} />
            )}

            {Object.keys(node.metadata).length > 0 && (
              <Section title="Metadata">
                <dl className="space-y-1">
                  {Object.entries(node.metadata)
                    .filter(
                      ([, v]) =>
                        v !== null &&
                        v !== undefined &&
                        !(Array.isArray(v) && v.length === 0)
                    )
                    .map(([k, v]) => (
                      <div
                        key={k}
                        className="flex items-start justify-between gap-3 text-[11px]"
                      >
                        <dt className="text-muted-foreground">
                          {k.replace(/_/g, " ")}
                        </dt>
                        <dd className="max-w-[60%] truncate text-right font-medium">
                          {typeof v === "object"
                            ? JSON.stringify(v)
                            : String(v)}
                        </dd>
                      </div>
                    ))}
                </dl>
              </Section>
            )}
          </div>
        </ScrollArea>

        <div className="border-t border-zinc-100 px-4 py-2.5 dark:border-zinc-800">
          <Link
            href={config.href(node.id)}
            className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Open full page
            <ExternalLink className="h-3 w-3" />
          </Link>
        </div>
      </div>
    </div>
  );
}

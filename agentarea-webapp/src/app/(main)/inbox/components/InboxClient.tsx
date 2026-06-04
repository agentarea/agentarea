"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  Bot,
  Check,
  CheckCircle2,
  Clock,
  FileText,
  Inbox as InboxIcon,
  Wallet,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { formatDistanceToNowStrict } from "date-fns";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { resolveEscalationAction } from "@/lib/server-actions";
import type { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";

type FilterValue = "all" | "pending" | "completed" | "failed";

const FILTERS: { key: FilterValue; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Needs approval" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
];

const STATUS_LABEL: Record<string, string> = {
  pending: "Needs approval",
  completed: "Completed",
  failed: "Failed",
};

// A task is "pending" (awaiting human approval) when its workflow paused on an
// escalation. The inbox API reports this as `waiting_for_approval`.
function isPending(status: string): boolean {
  return status === "waiting_for_approval" || status === "pending";
}

function normalizeStatus(status: string): "pending" | "completed" | "failed" {
  if (isPending(status)) return "pending";
  if (status === "completed" || status === "success") return "completed";
  return "failed";
}

// Deterministic agent chip color so the same agent reads the same across rows.
const AGENT_COLORS = [
  "#d99a00",
  "#5e6ad2",
  "#27a08c",
  "#d4519e",
  "#2252b3",
  "#c2683c",
  "#7c7ae6",
];
function agentColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return AGENT_COLORS[Math.abs(hash) % AGENT_COLORS.length];
}

function formatRelative(dateStr?: string | null): string {
  if (!dateStr) return "";
  try {
    return formatDistanceToNowStrict(new Date(dateStr), { addSuffix: true });
  } catch {
    return "";
  }
}

function fmtCost(cost?: number | null): string {
  return cost == null ? "—" : `$${Number(cost).toFixed(4)}`;
}

function StatusIcon({ status, size = 18 }: { status: string; size?: number }) {
  const cls = "shrink-0";
  switch (normalizeStatus(status)) {
    case "pending":
      return <Clock size={size} className={cn(cls, "text-amber-500")} />;
    case "completed":
      return <CheckCircle2 size={size} className={cn(cls, "text-emerald-500")} />;
    default:
      return <XCircle size={size} className={cn(cls, "text-red-500")} />;
  }
}

function AgentChip({ name }: { name: string }) {
  const color = agentColor(name);
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <span
        className="grid h-[15px] w-[15px] shrink-0 place-items-center rounded-[4px] text-[8px] font-bold text-white"
        style={{ background: color }}
      >
        {name.charAt(0).toUpperCase()}
      </span>
      <span className="truncate font-mono text-[11px] text-foreground/80">{name}</span>
    </span>
  );
}

interface InboxClientProps {
  items: TaskWithAgent[];
  error: string | null;
  initialFilter: FilterValue;
}

export function InboxClient({ items, error, initialFilter }: InboxClientProps) {
  const router = useRouter();
  const [filter, setFilter] = useState<FilterValue>(initialFilter);
  const [selId, setSelId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // Optimistic resolutions keyed by task id so the queue updates instantly.
  const [resolved, setResolved] = useState<Record<string, "completed" | "failed">>({});
  const [, startTransition] = useTransition();

  // Fresh server data invalidates any optimistic state we were holding.
  useEffect(() => {
    setResolved({});
    setChecked(new Set());
  }, [items]);

  const effectiveStatus = (t: TaskWithAgent): string => resolved[String(t.id)] ?? t.status;

  const counts = useMemo(() => {
    const c = { all: items.length, pending: 0, completed: 0, failed: 0 };
    for (const t of items) c[normalizeStatus(effectiveStatus(t))]++;
    return c;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, resolved]);

  const visible = useMemo(() => {
    return items.filter((t) =>
      filter === "all" ? true : normalizeStatus(effectiveStatus(t)) === filter
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items, filter, resolved]);

  const pendingSpend = useMemo(
    () =>
      items
        .filter((t) => normalizeStatus(effectiveStatus(t)) === "pending")
        .reduce((s, t) => s + (Number((t as any).total_cost) || 0), 0),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [items, resolved]
  );

  // Default selection: first task in the active view.
  useEffect(() => {
    if (selId && visible.some((t) => String(t.id) === selId)) return;
    setSelId(visible.length ? String(visible[0].id) : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const selected = visible.find((t) => String(t.id) === selId) ?? null;

  function changeFilter(next: FilterValue) {
    setFilter(next);
    setChecked(new Set());
    setSelId(null);
  }

  function toggleCheck(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function resolveOne(task: TaskWithAgent, approved: boolean) {
    const id = String(task.id);
    // No escalation handle (shouldn't happen for waiting_for_approval) — open the
    // task so the operator can resolve it in context rather than failing silently.
    if (!task.escalation_id) {
      router.push(`/tasks/${id}`);
      return;
    }
    // Advance selection off the row we're resolving before it leaves the queue.
    if (selId === id) {
      const next = visible.find((t) => String(t.id) !== id);
      setSelId(next ? String(next.id) : null);
    }
    setResolved((prev) => ({ ...prev, [id]: approved ? "completed" : "failed" }));
    setChecked((prev) => {
      const n = new Set(prev);
      n.delete(id);
      return n;
    });
    try {
      const { error: err } = await resolveEscalationAction(
        task.agent_id,
        id,
        task.escalation_id,
        approved,
        ""
      );
      if (err) throw err;
      startTransition(() => router.refresh());
    } catch (e) {
      console.error("Failed to resolve escalation:", e);
      // Roll back so the task reappears in the queue.
      setResolved((prev) => {
        const n = { ...prev };
        delete n[id];
        return n;
      });
    }
  }

  async function resolveMany(tasks: TaskWithAgent[], approved: boolean) {
    const targets = tasks.filter((t) => isPending(effectiveStatus(t)) && t.escalation_id);
    if (!targets.length) return;
    setResolved((prev) => {
      const n = { ...prev };
      for (const t of targets) n[String(t.id)] = approved ? "completed" : "failed";
      return n;
    });
    setChecked(new Set());
    setSelId(null);
    try {
      await Promise.all(
        targets.map((t) =>
          resolveEscalationAction(t.agent_id, String(t.id), t.escalation_id as string, approved, "")
        )
      );
      startTransition(() => router.refresh());
    } catch (e) {
      console.error("Failed to resolve escalations:", e);
      startTransition(() => router.refresh());
    }
  }

  const pendingTasks = items.filter((t) => isPending(effectiveStatus(t)) && t.escalation_id);
  const anyChecked = checked.size > 0;

  const toolbar = (
    <div className="flex h-[46px] w-full items-center gap-3">
      <div className="inline-flex rounded-lg bg-muted p-[3px]">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => changeFilter(f.key)}
            className={cn(
              "inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-[12.5px] font-medium transition-colors",
              filter === f.key
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {f.label}
            <span
              className={cn(
                "text-[11px] font-semibold",
                filter === f.key ? "text-muted-foreground" : "text-muted-foreground/70"
              )}
            >
              {counts[f.key]}
            </span>
          </button>
        ))}
      </div>
      <div className="flex-1" />
      <div className="text-[12.5px] text-muted-foreground">
        {filter === "pending" ? (
          <>
            <b className="font-semibold text-foreground">{counts.pending}</b> awaiting approval ·{" "}
            <b className="font-semibold text-foreground">${pendingSpend.toFixed(4)}</b> pending spend
          </>
        ) : (
          <>
            <b className="font-semibold text-foreground">{visible.length}</b>{" "}
            {filter === "all" ? "tasks" : STATUS_LABEL[filter].toLowerCase()}
          </>
        )}
      </div>
    </div>
  );

  const approveAll =
    filter === "pending" && pendingTasks.length > 0 ? (
      <button
        onClick={() => resolveMany(pendingTasks, true)}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-primary-foreground shadow-sm transition hover:brightness-95"
      >
        <Check size={14} strokeWidth={2.4} /> Approve all
      </button>
    ) : null;

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Inbox" }], controls: approveAll }}
      subheader={toolbar}
      className="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      {error ? (
        <div className="flex flex-1 items-center justify-center text-sm text-red-500">{error}</div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden lg:grid-cols-[1fr_432px]">
          {/* ---- list pane ---- */}
          <div className="flex min-w-0 flex-col overflow-hidden border-r border-border">
            {anyChecked && (
              <div className="flex shrink-0 items-center gap-3 border-b border-border bg-primary/10 px-4 py-2">
                <span className="text-[12.5px] font-semibold text-primary">
                  {checked.size} selected
                </span>
                <div className="flex-1" />
                <button
                  onClick={() =>
                    resolveMany(
                      items.filter((t) => checked.has(String(t.id))),
                      true
                    )
                  }
                  className="inline-flex h-7 items-center gap-1.5 rounded-md bg-emerald-600 px-3 text-[12.5px] font-semibold text-white transition hover:brightness-95"
                >
                  <Check size={14} strokeWidth={2.4} /> Approve
                </button>
                <button
                  onClick={() =>
                    resolveMany(
                      items.filter((t) => checked.has(String(t.id))),
                      false
                    )
                  }
                  className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-3 text-[12.5px] font-semibold text-red-500 transition hover:bg-red-500/5"
                >
                  <X size={14} strokeWidth={2.4} /> Reject
                </button>
                <button
                  onClick={() => setChecked(new Set())}
                  className="px-1 text-[12.5px] font-medium text-muted-foreground hover:text-foreground"
                >
                  Clear
                </button>
              </div>
            )}

            <div className="min-h-0 flex-1 overflow-y-auto">
              {visible.length === 0 ? (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  Nothing here.
                </div>
              ) : (
                visible.map((t) => {
                  const id = String(t.id);
                  const status = effectiveStatus(t);
                  const pend = isPending(status);
                  const isSel = id === selId;
                  const isChecked = checked.has(id);
                  return (
                    <div
                      key={id}
                      onClick={() => setSelId(id)}
                      className={cn(
                        "group relative flex cursor-pointer items-center gap-3 border-b border-border/60 px-4 py-2.5 transition-colors",
                        isSel ? "bg-primary/10" : "hover:bg-muted/60"
                      )}
                    >
                      {isSel && (
                        <span className="absolute inset-y-0 left-0 w-[2px] bg-primary" />
                      )}

                      {pend && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleCheck(id);
                          }}
                          className={cn(
                            "grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border transition",
                            isChecked
                              ? "border-primary bg-primary text-white opacity-100"
                              : "border-muted-foreground/50 text-transparent",
                            !isChecked && !anyChecked && "opacity-0 group-hover:opacity-100"
                          )}
                          aria-label="Select task"
                        >
                          <Check size={11} strokeWidth={3} />
                        </button>
                      )}

                      <StatusIcon status={status} />

                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-semibold">
                          {t.description || "Untitled task"}
                        </p>
                        <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-muted-foreground">
                          <AgentChip name={(t as any).agent_name || "Unknown agent"} />
                          <span className="h-[3px] w-[3px] shrink-0 rounded-full bg-muted-foreground/50" />
                          <span className="whitespace-nowrap">{formatRelative(t.created_at)}</span>
                        </div>
                      </div>

                      <div className="flex shrink-0 items-center gap-3">
                        <span className="w-[62px] text-right font-mono text-[11.5px] text-muted-foreground">
                          {fmtCost((t as any).total_cost)}
                        </span>
                        {pend && (
                          <div className="flex items-center gap-1.5 opacity-0 transition group-hover:opacity-100">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                resolveOne(t, true);
                              }}
                              title="Approve"
                              className="grid h-7 w-7 place-items-center rounded-md border border-border bg-background text-emerald-600 hover:border-emerald-500 hover:bg-emerald-500/10"
                            >
                              <Check size={15} strokeWidth={2} />
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                resolveOne(t, false);
                              }}
                              title="Reject"
                              className="grid h-7 w-7 place-items-center rounded-md border border-border bg-background text-red-500 hover:border-red-500 hover:bg-red-500/10"
                            >
                              <X size={15} strokeWidth={2} />
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          {/* ---- detail pane ---- */}
          <aside className="hidden min-w-0 flex-col overflow-y-auto lg:flex">
            <DetailPane task={selected} onResolve={resolveOne} />
          </aside>
        </div>
      )}
    </ContentBlock>
  );
}

function DetailPane({
  task,
  onResolve,
}: {
  task: TaskWithAgent | null;
  onResolve: (task: TaskWithAgent, approved: boolean) => void;
}) {
  if (!task) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-10 text-center text-sm text-muted-foreground">
        <InboxIcon size={40} strokeWidth={1.4} className="mb-3 text-muted-foreground/60" />
        <div>
          Select a task to review its output
          <br />
          and approve or reject the action.
        </div>
      </div>
    );
  }

  const status = task.status;
  const pend = isPending(status);
  const norm = normalizeStatus(status);
  const agentName = (task as any).agent_name || "Unknown agent";
  const color = agentColor(agentName);
  const result = task.result;
  const resultText =
    typeof result === "string"
      ? result
      : result && Object.keys(result).length
        ? JSON.stringify(result, null, 2)
        : null;

  const statusPillCls =
    norm === "pending"
      ? "text-amber-600 bg-amber-500/10 dark:text-amber-400"
      : norm === "completed"
        ? "text-emerald-700 bg-emerald-500/10 dark:text-emerald-400"
        : "text-red-700 bg-red-500/10 dark:text-red-400";

  return (
    <>
      <div className="flex-1 px-5 pt-5">
        <span
          className={cn(
            "mb-3 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold",
            statusPillCls
          )}
        >
          <StatusIcon status={status} size={14} /> {STATUS_LABEL[norm]}
        </span>

        <h2 className="mb-3.5 text-[19px] font-semibold leading-tight tracking-tight">
          {task.description || "Untitled task"}
        </h2>

        <div className="mb-[18px] grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-2 text-[12.5px]">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Bot size={15} /> Agent
          </div>
          <div className="text-right font-medium">
            <span
              className="mr-1.5 inline-grid h-4 w-4 place-items-center rounded-[4px] align-[-3px] text-[8px] font-bold text-white"
              style={{ background: color }}
            >
              {agentName.charAt(0).toUpperCase()}
            </span>
            {agentName}
          </div>

          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock size={15} /> Requested
          </div>
          <div className="text-right font-medium">{formatRelative(task.created_at)}</div>

          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Wallet size={15} /> Cost
          </div>
          <div className="text-right font-mono">{fmtCost((task as any).total_cost)}</div>
        </div>

        {pend && (
          <div className="mb-4 flex items-start gap-2.5 rounded-[9px] bg-amber-500/10 px-3 py-2.5 text-[12.5px] leading-relaxed text-foreground/80">
            <Zap size={16} className="mt-px shrink-0 text-amber-500" />
            <div>
              On approval, the agent will run{" "}
              <b className="font-semibold text-foreground">
                {task.escalation_tool_name || "the requested action"}
              </b>
              .
            </div>
          </div>
        )}

        <p className="mb-2 text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground/70">
          Output preview
        </p>
        <div className="mb-5 overflow-hidden rounded-[10px] border border-border">
          <div className="flex items-center gap-1.5 border-b border-border/60 bg-muted/50 px-3 py-2 text-[11px] font-semibold text-muted-foreground">
            <FileText size={13} /> result.txt
          </div>
          <div className="whitespace-pre-wrap px-3 py-3 font-mono text-[11.5px] leading-relaxed text-foreground/80">
            {resultText ?? (pend ? "Output will be available after the action runs." : "(no output)")}
          </div>
        </div>
      </div>

      <div className="sticky bottom-0 border-t border-border bg-background px-5 py-3">
        {pend ? (
          <div className="flex gap-2.5">
            <button
              onClick={() => onResolve(task, false)}
              className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background text-[13px] font-semibold text-red-500 transition hover:border-red-500 hover:bg-red-500/10"
            >
              <X size={16} strokeWidth={2} /> Reject
            </button>
            <button
              onClick={() => onResolve(task, true)}
              className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 text-[13px] font-semibold text-white shadow-sm transition hover:brightness-95"
            >
              <Check size={16} strokeWidth={2.2} /> Approve
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 py-1.5 text-[12.5px] text-muted-foreground">
            <StatusIcon status={status} size={16} /> This task is {STATUS_LABEL[norm].toLowerCase()} —
            no action needed.
          </div>
        )}
      </div>
    </>
  );
}

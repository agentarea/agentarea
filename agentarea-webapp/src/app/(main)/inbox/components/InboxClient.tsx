"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatDistanceToNowStrict } from "date-fns";
import {
  Bot,
  Check,
  CheckCircle2,
  Clock,
  ExternalLink,
  Inbox as InboxIcon,
  ScrollText,
  ShieldCheck,
  Wallet,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { AgentAvatar } from "@/components/AgentAvatar";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import type { TaskWithAgent } from "@/lib/api";
import { resolveEscalationAction } from "@/lib/server-actions";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getInboxStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";

const FILTER_KEYS = ["all", "pending", "completed", "failed"] as const;
type FilterValue = (typeof FILTER_KEYS)[number];

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
      return (
        <CheckCircle2 size={size} className={cn(cls, "text-emerald-500")} />
      );
    default:
      return <XCircle size={size} className={cn(cls, "text-red-500")} />;
  }
}

function AgentChip({ id, name }: { id?: string | null; name: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <AgentAvatar agent={{ id: id || name, name }} size="xs" />
      <span className="truncate font-mono text-[11px] text-foreground/80">
        {name}
      </span>
    </span>
  );
}

interface InboxClientProps {
  items: TaskWithAgent[];
  error: string | null;
}

export function InboxClient({ items, error }: InboxClientProps) {
  const router = useRouter();
  const [filter, setFilter] = useQueryState(
    "filter",
    parseAsStringLiteral(FILTER_KEYS).withDefault("all")
  );
  const [selId, setSelId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // Optimistic resolutions keyed by task id so the queue updates instantly.
  const [resolved, setResolved] = useState<
    Record<string, "completed" | "failed">
  >({});
  const [, startTransition] = useTransition();

  // Fresh server data invalidates any optimistic state we were holding.
  useEffect(() => {
    setResolved({});
    setChecked(new Set());
  }, [items]);

  const effectiveStatus = (t: TaskWithAgent): string =>
    resolved[String(t.id)] ?? t.status;

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
    setResolved((prev) => ({
      ...prev,
      [id]: approved ? "completed" : "failed",
    }));
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
    const targets = tasks.filter(
      (t) => isPending(effectiveStatus(t)) && t.escalation_id
    );
    if (!targets.length) return;
    setResolved((prev) => {
      const n = { ...prev };
      for (const t of targets)
        n[String(t.id)] = approved ? "completed" : "failed";
      return n;
    });
    setChecked(new Set());
    setSelId(null);
    try {
      await Promise.all(
        targets.map((t) =>
          resolveEscalationAction(
            t.agent_id,
            String(t.id),
            t.escalation_id as string,
            approved,
            ""
          )
        )
      );
      startTransition(() => router.refresh());
    } catch (e) {
      console.error("Failed to resolve escalations:", e);
      startTransition(() => router.refresh());
    }
  }

  const pendingTasks = items.filter(
    (t) => isPending(effectiveStatus(t)) && t.escalation_id
  );
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
                filter === f.key
                  ? "text-muted-foreground"
                  : "text-muted-foreground/70"
              )}
            >
              {counts[f.key]}
            </span>
          </button>
        ))}
      </div>
      <div className="flex-1" />
      {filter !== "pending" || counts.pending > 0 ? (
        <div className="text-[12.5px] text-muted-foreground">
          {filter === "pending" ? (
            <>
              <b className="font-semibold text-foreground">{counts.pending}</b>{" "}
              awaiting approval
            </>
          ) : (
            <>
              <b className="font-semibold text-foreground">{visible.length}</b>{" "}
              {filter === "all" ? "tasks" : STATUS_LABEL[filter].toLowerCase()}
            </>
          )}
        </div>
      ) : null}
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
        <div className="flex flex-1 items-center justify-center text-sm text-red-500">
          {error}
        </div>
      ) : (
        <div
          className={cn(
            "grid min-h-0 flex-1 grid-cols-1 overflow-hidden",
            selected && "lg:grid-cols-[1fr_432px]"
          )}
        >
          {/* ---- list pane ---- */}
          <div
            className={cn(
              "flex min-w-0 flex-col overflow-hidden",
              selected && "border-r border-border"
            )}
          >
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
                <InboxEmptyState filter={filter} counts={counts} />
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
                            !isChecked &&
                              !anyChecked &&
                              "opacity-0 group-hover:opacity-100"
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
                          <AgentChip
                            id={t.agent_id}
                            name={(t as any).agent_name || "Unknown agent"}
                          />
                          <span className="h-[3px] w-[3px] shrink-0 rounded-full bg-muted-foreground/50" />
                          <span className="whitespace-nowrap">
                            {formatRelative(t.created_at)}
                          </span>
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
          {selected && (
            <aside className="hidden min-w-0 flex-col overflow-y-auto lg:flex">
              <DetailPane task={selected} onResolve={resolveOne} />
            </aside>
          )}
        </div>
      )}
    </ContentBlock>
  );
}

function InboxEmptyState({
  filter,
  counts,
}: {
  filter: FilterValue;
  counts: Record<FilterValue, number>;
}) {
  const copy: Record<
    FilterValue,
    { title: string; description: string; Icon: typeof InboxIcon }
  > = {
    all: {
      title: "No inbox decisions yet",
      description:
        "When an agent needs approval, completes a governed action, or fails a controlled step, it will appear here for review.",
      Icon: InboxIcon,
    },
    pending: {
      title: "Approval queue is clear",
      description:
        "No agent is waiting on a human decision right now. New escalations will land here before they can continue.",
      Icon: CheckCircle2,
    },
    completed: {
      title: "No completed approvals",
      description:
        "Approved actions will appear here after operators release them, so you can audit what moved forward.",
      Icon: CheckCircle2,
    },
    failed: {
      title: "No rejected or failed approvals",
      description:
        "Rejected actions and failed escalations will appear here when a governed path is stopped.",
      Icon: XCircle,
    },
  };
  const { title, description, Icon } = copy[filter];

  return (
    <div className="flex h-full items-center justify-center px-6 py-10">
      <div className="flex max-w-[560px] flex-col items-center text-center">
        <InboxEmptyIllustration Icon={Icon} />
        <h2 className="mt-4 text-[15px] font-semibold text-foreground">
          {title}
        </h2>
        <p className="mt-1.5 max-w-[460px] text-[13px] leading-6 text-muted-foreground">
          {description}
        </p>

        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {filter !== "all" && counts.all > 0 && (
            <Link
              href="/inbox"
              className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-[12.5px] font-medium text-foreground transition hover:bg-muted"
            >
              View all
            </Link>
          )}
          <Link
            href="/tasks"
            className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-[12.5px] font-medium text-foreground transition hover:bg-muted"
          >
            Open task history
          </Link>
          <Link
            href="/triggers"
            className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-[12.5px] font-medium text-foreground transition hover:bg-muted"
          >
            Check triggers
          </Link>
        </div>
      </div>
    </div>
  );
}

function InboxEmptyIllustration({ Icon }: { Icon: typeof InboxIcon }) {
  return (
    <div className="relative flex h-[72px] w-[260px] items-center justify-center text-muted-foreground">
      <div className="absolute left-[58px] right-[58px] top-1/2 h-px bg-border" />
      <div className="relative z-10 grid h-11 w-11 place-items-center rounded-lg border border-border bg-background shadow-sm">
        <Bot size={20} strokeWidth={1.8} />
      </div>
      <div className="relative z-10 mx-5 grid h-12 w-12 place-items-center rounded-lg border border-primary/25 bg-primary/5 text-primary shadow-sm">
        <ShieldCheck size={22} strokeWidth={1.8} />
      </div>
      <div className="relative z-10 grid h-11 w-11 place-items-center rounded-lg border border-border bg-background shadow-sm">
        {Icon === InboxIcon ? (
          <ScrollText size={20} strokeWidth={1.8} />
        ) : (
          <Icon size={20} strokeWidth={1.8} />
        )}
      </div>
    </div>
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
        <InboxIcon
          size={40}
          strokeWidth={1.4}
          className="mb-3 text-muted-foreground/60"
        />
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
  const presentation = getInboxStatusPresentation(status);
  const agentName = (task as any).agent_name || "Unknown agent";
  const result = task.result;
  const resultText =
    typeof result === "string"
      ? result
      : result && Object.keys(result).length
        ? JSON.stringify(result, null, 2)
        : null;

  return (
    <>
      <div className="flex-1 px-5 pt-5">
        <StatusIndicator
          size="sm"
          tone={presentation.tone}
          pulse={presentation.pulse}
          className="mb-3 whitespace-nowrap"
        >
          {presentation.label}
        </StatusIndicator>

        <div className="mb-3.5 flex items-start justify-between gap-2">
          <h2 className="text-[19px] font-semibold leading-tight tracking-tight">
            {task.description || "Untitled task"}
          </h2>
          <Link
            href={`/tasks/${task.id}`}
            className="mt-0.5 shrink-0 inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11.5px] font-medium text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors"
          >
            <ExternalLink size={12} /> Open
          </Link>
        </div>

        <div className="mb-[18px] grid grid-cols-[auto_1fr] gap-x-3.5 gap-y-2 text-[12.5px]">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Bot size={15} /> Agent
          </div>
          <div className="inline-flex items-center justify-end gap-1.5 text-right font-medium">
            <AgentAvatar
              agent={{ id: task.agent_id || agentName, name: agentName }}
              size="xs"
            />
            {agentName}
          </div>

          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock size={15} /> Requested
          </div>
          <div className="text-right font-medium">
            {formatRelative(task.created_at)}
          </div>

          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Wallet size={15} /> Cost
          </div>
          <div className="text-right font-mono">
            {fmtCost((task as any).total_cost)}
          </div>
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
          Output
        </p>
        <div className="mb-5 overflow-hidden rounded-[10px] border border-border bg-muted/30">
          <div className="whitespace-pre-wrap px-3 py-3 font-mono text-[11.5px] leading-relaxed text-foreground/80">
            {resultText ?? (
              <span className="text-muted-foreground/60 italic">
                {pend
                  ? "Output will be available after the action runs."
                  : "No output."}
              </span>
            )}
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
            <StatusIndicator
              size="sm"
              tone={presentation.tone}
              pulse={presentation.pulse}
              className="whitespace-nowrap"
            >
              {presentation.label}
            </StatusIndicator>
            <span>
              This task is {STATUS_LABEL[norm].toLowerCase()} — no action needed.
            </span>
          </div>
        )}
      </div>
    </>
  );
}

"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { formatDistanceToNowStrict } from "date-fns";
import {
  Bot,
  Check,
  CheckCircle2,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { AgentAvatar } from "@/components/AgentAvatar";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { InboxClientPanel } from "@/app/(main)/inbox/components/InboxClientPanel";
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

function InboxStatusMark({ status }: { status: string }) {
  const presentation = getInboxStatusPresentation(status);

  return (
    <StatusIndicator
      tone={presentation.tone}
      pulse={presentation.pulse}
      size="default"
      aria-label={presentation.label}
      title={presentation.label}
      className="mt-1 shrink-0"
    />
  );
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
  const [isCompactLayout, setIsCompactLayout] = useState(false);
  const [selId, setSelId] = useState<string | null>(null);
  const [desktopPanelTask, setDesktopPanelTask] = useState<TaskWithAgent | null>(
    null
  );
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

  useEffect(() => {
    const mql = window.matchMedia("(max-width: 1023px)");
    const onChange = () => setIsCompactLayout(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

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
  const desktopPanelOpen = !isCompactLayout && Boolean(selected);

  useEffect(() => {
    if (isCompactLayout) {
      setDesktopPanelTask(null);
      return;
    }

    if (selected) {
      setDesktopPanelTask(selected);
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setDesktopPanelTask(null);
    }, 220);

    return () => window.clearTimeout(timeoutId);
  }, [isCompactLayout, selected]);

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
      <CountSegmentedControl
        items={FILTERS.map((item) => ({
          value: item.key,
          label: item.label,
          count: counts[item.key],
        }))}
        value={filter}
        onChange={changeFilter}
        layoutId="inbox-filter-control"
      />
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
          className="flex min-h-0 flex-1 overflow-hidden"
        >
          <Sheet
            open={isCompactLayout && Boolean(selected)}
            onOpenChange={(open) => {
              if (!open) setSelId(null);
            }}
          >
            <SheetContent
              side="right"
              className="flex w-full flex-col p-0 sm:max-w-[432px] lg:hidden [&>button]:hidden"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>Inbox task details</SheetTitle>
                <SheetDescription>
                  Review task output and approve or reject the action.
                </SheetDescription>
              </SheetHeader>
              <InboxClientPanel
                task={selected}
                onResolve={resolveOne}
                onClose={() => setSelId(null)}
              />
            </SheetContent>
          </Sheet>

          {/* ---- list pane ---- */}
          <div
            className={cn(
              "flex min-w-0 flex-1 flex-col overflow-hidden",
              desktopPanelTask && "border-r border-zinc-200 dark:border-zinc-700"
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
                  const presentation = getInboxStatusPresentation(status);
                  const pend = isPending(status);
                  const isSel = id === selId;
                  const isChecked = checked.has(id);
                  return (
                    <InteractiveListRow
                      key={id}
                      onClick={() => setSelId(id)}
                      selected={isSel}
                      className="items-start"
                      decorationTone={presentation.tone}
                      decorationVisible={isSel}
                      start={
                        <>
                          {pend && (
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                toggleCheck(id);
                              }}
                              className={cn(
                                "mt-1 grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border transition",
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
                          <InboxStatusMark status={status} />
                        </>
                      }
                      end={
                        <span className="w-[62px] text-right font-mono text-[11.5px] text-muted-foreground">
                          {fmtCost((t as any).total_cost)}
                        </span>
                      }
                      hoverActions={
                        pend ? (
                          <>
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
                          </>
                        ) : null
                      }
                    >
                      <div className="min-w-0 flex-1 pt-0">
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
                    </InteractiveListRow>
                  );
                })
              )}
            </div>
          </div>

          {/* ---- detail pane ---- */}
          <aside
            className="relative hidden shrink-0 overflow-hidden transition-[width] duration-200 ease-out lg:block"
            style={{ width: desktopPanelOpen ? 432 : 0 }}
          >
            {desktopPanelTask && (
              <div
                className={cn(
                  "absolute inset-y-0 right-0 flex w-[432px] min-w-0 flex-col overflow-y-auto border-l border-border bg-background transition-all duration-200 ease-out",
                  desktopPanelOpen
                    ? "translate-x-0 opacity-100"
                    : "translate-x-6 opacity-0 pointer-events-none"
                )}
              >
                <InboxClientPanel
                  task={desktopPanelTask}
                  onResolve={resolveOne}
                  onClose={() => setSelId(null)}
                />
              </div>
            )}
          </aside>
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
    {
      title: string;
      description: string;
      icons: LucideIcon[];
      buttons: { label: string; href: string }[];
    }
  > = {
    all: {
      title: "No inbox decisions yet",
      description:
        "When an agent needs approval, completes a governed action, or fails a controlled step, it will appear here for review.",
      icons: [Bot, ShieldCheck, ScrollText],
      buttons: [
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    pending: {
      title: "Approval queue is clear",
      description:
        "No agent is waiting on a human decision right now. New escalations will land here before they can continue.",
      icons: [Bot, ShieldAlert, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    completed: {
      title: "No completed approvals",
      description:
        "Approved actions will appear here after operators release them, so you can audit what moved forward.",
      icons: [CheckCircle2, ShieldCheck, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
    failed: {
      title: "No rejected or failed approvals",
      description:
        "Rejected actions and failed escalations will appear here when a governed path is stopped.",
      icons: [XCircle, ShieldAlert, ScrollText],
      buttons: [
        ...(counts.all > 0 ? [{ label: "View all", href: "/inbox" }] : []),
        { label: "Open task history", href: "/tasks" },
        { label: "Check triggers", href: "/triggers" },
      ],
    },
  };
  const { title, description, icons, buttons } = copy[filter];
  const [action, additionAction, tertiaryAction] = buttons;

  return (
    <div className="flex h-full justify-center px-6 py-10">
      <div className="flex w-full flex-col gap-3">
        <EmptyState
          title={title}
          description={description}
          icons={icons}
          action={
            action
              ? {
                  label: action.label,
                  href: action.href,
                }
              : undefined
          }
          additionAction={
            additionAction
              ? {
                  label: additionAction.label,
                  href: additionAction.href,
                }
              : undefined
          }
        />
        {/* {tertiaryAction && (
          <div className="flex justify-center">
            <Link
              href={tertiaryAction.href}
              className="inline-flex h-8 items-center justify-center rounded-md px-3 text-[12.5px] font-medium text-muted-foreground transition hover:text-foreground"
            >
              {tertiaryAction.label}
            </Link>
          </div>
        )} */}
      </div>
    </div>
  );
}

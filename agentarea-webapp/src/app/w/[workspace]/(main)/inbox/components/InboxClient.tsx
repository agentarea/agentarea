"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { InboxBatchDecisionDialog } from "@/app/w/[workspace]/(main)/inbox/components/InboxBatchDecisionDialog";
import { InboxClientPanel } from "@/app/w/[workspace]/(main)/inbox/components/InboxClientPanel";
import { InboxDecisionList } from "@/app/w/[workspace]/(main)/inbox/components/InboxDecisionList";
import { InboxDetailEmpty } from "@/app/w/[workspace]/(main)/inbox/components/InboxDetailEmpty";
import { InboxEmptyState } from "@/app/w/[workspace]/(main)/inbox/components/InboxEmptyState";
import { InboxSelectionBar } from "@/app/w/[workspace]/(main)/inbox/components/InboxSelectionBar";
import {
  countInbox,
  FILTER_KEYS,
  inboxBucket,
  isPending,
  RESOLVED_ESCALATION_STATUS,
  type FilterValue,
  type InboxDecision,
  type InboxTask,
} from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import { InboxTaskList } from "@/app/w/[workspace]/(main)/inbox/components/InboxTaskList";
import { InboxToolbar } from "@/app/w/[workspace]/(main)/inbox/components/InboxToolbar";
import type { ApprovalDecisionResult } from "@/components/Approvals/ApprovalDecisionCard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import FormError from "@/components/FormError";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { resolveEscalationAction } from "@/lib/server-actions";

interface InboxClientProps {
  items: InboxTask[];
  error: string | null;
  decisions: InboxDecision[];
  decisionsTotal: number;
  decisionsError: string | null;
}

type BatchDecision = { approved: boolean; tasks: InboxTask[] };

export function InboxClient({
  items,
  error,
  decisions,
  decisionsTotal,
  decisionsError,
}: InboxClientProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("InboxPage");
  const [filter, setFilter] = useQueryState(
    "filter",
    parseAsStringLiteral(FILTER_KEYS).withDefault("all")
  );
  const [isCompactLayout, setIsCompactLayout] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [resolved, setResolved] = useState<
    Record<string, typeof RESOLVED_ESCALATION_STATUS>
  >({});
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchDecision | null>(null);
  const [, startTransition] = useTransition();

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

  const effectiveStatus = useCallback(
    (task: InboxTask): string => resolved[String(task.id)] ?? task.status,
    [resolved]
  );

  const { counts, unknown } = useMemo(
    () => countInbox(items.map(effectiveStatus), decisionsTotal),
    [items, effectiveStatus, decisionsTotal]
  );

  useEffect(() => {
    if (unknown.length > 0) {
      console.error("Inbox returned statuses it has no filter for", unknown);
    }
  }, [unknown]);

  const showingDecisions = filter === "decided";
  const visible = useMemo(() => {
    if (filter === "decided") return [];
    return items.filter((task) =>
      filter === "all" ? true : inboxBucket(effectiveStatus(task)) === filter
    );
  }, [items, filter, effectiveStatus]);

  const selected =
    visible.find((task) => String(task.id) === selectedId) ?? null;
  // Keep the reading surface in sync with an optimistic resolve so the action
  // footer never offers controls for a task that has already been handled.
  const selectedWithEffectiveStatus = selected
    ? { ...selected, status: effectiveStatus(selected) }
    : null;
  const decidable = (task: InboxTask) =>
    isPending(effectiveStatus(task)) && Boolean(task.escalation_id);
  const pendingTasks = items.filter(decidable);
  const anyChecked = checked.size > 0;

  function changeFilter(next: FilterValue) {
    setFilter(next);
    setChecked(new Set());
    setSelectedId(null);
  }

  // Jump to the first task still waiting on a decision; a filter that hides
  // it (completed / failed / decided) switches to the approval queue first.
  function openNextPending() {
    const next = items.find((task) => isPending(effectiveStatus(task)));
    if (!next) return;
    if (filter !== "all" && filter !== "pending") changeFilter("pending");
    setSelectedId(String(next.id));
  }

  function toggleCheck(id: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function resolveOne(
    task: InboxTask,
    approved: boolean,
    comment = "",
    escalationId = task.escalation_id
  ): Promise<ApprovalDecisionResult> {
    const id = String(task.id);

    if (!escalationId) {
      router.push(`/tasks/${id}`);
      return;
    }

    if (selectedId === id) {
      const next = visible.find((item) => String(item.id) !== id);
      setSelectedId(next ? String(next.id) : null);
    }

    setResolved((prev) => ({ ...prev, [id]: RESOLVED_ESCALATION_STATUS }));
    setChecked((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
    setResolveError(null);

    const label = t("resolveFailed", {
      task: task.description || t("row.untitled"),
    });
    const revert = () =>
      setResolved((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });

    try {
      const result = await resolveEscalationAction(
        task.agent_id,
        id,
        escalationId,
        approved,
        comment
      );
      if (result.error) {
        console.error("Failed to resolve escalation:", result.error);
        revert();
        setResolveError(apiErrorMessage(result, label));
        return result;
      }
      startTransition(() => router.refresh());
      return result;
    } catch (e) {
      console.error("Failed to resolve escalation:", e);
      revert();
      setResolveError(`${label}: ${formatApiError(e)}`);
      return { error: e };
    }
  }

  async function resolveMany(
    tasks: InboxTask[],
    approved: boolean,
    comment: string
  ) {
    const targets = tasks.filter(decidable);
    if (!targets.length) return;

    setResolved((prev) => {
      const next = { ...prev };
      for (const task of targets) {
        next[String(task.id)] = RESOLVED_ESCALATION_STATUS;
      }
      return next;
    });
    setChecked(new Set());
    setSelectedId(null);
    setResolveError(null);

    const outcomes = await Promise.allSettled(
      targets.map((task) =>
        resolveEscalationAction(
          task.agent_id,
          String(task.id),
          task.escalation_id as string,
          approved,
          comment
        )
      )
    );
    const failures: { task: InboxTask; reason: string }[] = [];
    outcomes.forEach((outcome, index) => {
      const task = targets[index];
      if (outcome.status === "rejected") {
        failures.push({ task, reason: formatApiError(outcome.reason) });
      } else if (outcome.value.error) {
        failures.push({ task, reason: formatApiError(outcome.value.error) });
      }
    });

    if (failures.length > 0) {
      console.error("Failed to resolve escalations:", failures);
      setResolved((prev) => {
        const next = { ...prev };
        for (const { task } of failures) delete next[String(task.id)];
        return next;
      });
      setResolveError(
        `${t("resolveManyFailed", {
          failed: failures.length,
          total: targets.length,
        })}: ${failures
          .map(
            ({ task, reason }) =>
              `${task.description || t("row.untitled")} (${reason})`
          )
          .join(", ")}`
      );
    }
    startTransition(() => router.refresh());
  }

  // Deciding several at once always shows each call first: the batch dialog
  // lists every tool and its arguments before anything is sent.
  function confirmBatch(tasks: InboxTask[], approved: boolean) {
    const targets = tasks.filter(decidable);
    if (targets.length) setBatch({ approved, tasks: targets });
  }

  const checkedTasks = items.filter((task) => checked.has(String(task.id)));

  const approveAll =
    filter === "pending" && pendingTasks.length > 0 ? (
      <button
        onClick={() => confirmBatch(pendingTasks, true)}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-semibold text-primary-foreground shadow-sm transition hover:brightness-95"
      >
        <Check size={14} strokeWidth={2.4} /> {t("approveAll")}
      </button>
    ) : null;

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }], controls: approveAll }}
      subheader={
        error ? undefined : (
          <InboxToolbar
            counts={counts}
            filter={filter}
            onChange={changeFilter}
          />
        )
      }
      className="flex min-h-0 flex-1 flex-col overflow-hidden p-0"
    >
      {error ? (
        <RetryEmptyState title={t("loadFailed")} description={error} />
      ) : (
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <Sheet
            open={isCompactLayout && Boolean(selected)}
            onOpenChange={(open) => {
              if (!open) setSelectedId(null);
            }}
          >
            <SheetContent
              side="right"
              // Full width inside the page frame (8px each side) on tablets.
              className="flex h-full w-full max-w-none flex-col p-0 sm:w-[calc(100%-1rem)] sm:max-w-none lg:hidden [&>button]:hidden"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>{t("sheet.title")}</SheetTitle>
                <SheetDescription>{t("sheet.description")}</SheetDescription>
              </SheetHeader>
              <InboxClientPanel
                task={selectedWithEffectiveStatus}
                onResolve={resolveOne}
                onClose={() => setSelectedId(null)}
              />
            </SheetContent>
          </Sheet>

          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:w-[40%] lg:min-w-[360px] lg:max-w-[520px] lg:flex-none lg:border-r lg:border-border">
            {anyChecked && (
              <InboxSelectionBar
                checkedCount={checked.size}
                onApprove={() => confirmBatch(checkedTasks, true)}
                onReject={() => confirmBatch(checkedTasks, false)}
                onClear={() => setChecked(new Set())}
              />
            )}

            {resolveError && (
              <FormError className="m-3 mb-0">{resolveError}</FormError>
            )}

            <div className="min-h-0 flex-1 overflow-y-auto">
              {showingDecisions ? (
                <InboxDecisionList
                  decisions={decisions}
                  error={decisionsError}
                  empty={<InboxEmptyState filter="decided" counts={counts} />}
                />
              ) : (
                <InboxTaskList
                  visible={visible}
                  filter={filter}
                  counts={counts}
                  selectedId={selectedId}
                  checked={checked}
                  anyChecked={anyChecked}
                  effectiveStatus={effectiveStatus}
                  onSelect={setSelectedId}
                  onToggleCheck={toggleCheck}
                  onResolve={(task, approved) => {
                    void resolveOne(task, approved);
                  }}
                />
              )}
            </div>
          </div>

          {!isCompactLayout && (
            <aside className="hidden min-h-0 min-w-0 flex-1 overflow-hidden bg-background lg:flex">
              {selectedWithEffectiveStatus ? (
                <InboxClientPanel
                  task={selectedWithEffectiveStatus}
                  onResolve={resolveOne}
                  onClose={() => setSelectedId(null)}
                />
              ) : (
                <InboxDetailEmpty
                  pendingCount={counts.pending}
                  onOpenNextPending={openNextPending}
                />
              )}
            </aside>
          )}
        </div>
      )}

      <InboxBatchDecisionDialog
        approved={batch?.approved ?? null}
        tasks={batch?.tasks ?? []}
        onCancel={() => setBatch(null)}
        onConfirm={(approved, comment) => {
          const tasks = batch?.tasks ?? [];
          setBatch(null);
          void resolveMany(tasks, approved, comment);
        }}
      />
    </ContentBlock>
  );
}

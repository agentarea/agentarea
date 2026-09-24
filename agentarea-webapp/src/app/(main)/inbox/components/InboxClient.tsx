"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  useTransition,
} from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Check } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import { InboxClientPanel } from "@/app/(main)/inbox/components/InboxClientPanel";
import { InboxDetailEmpty } from "@/app/(main)/inbox/components/InboxDetailEmpty";
import { InboxSelectionBar } from "@/app/(main)/inbox/components/InboxSelectionBar";
import {
  FILTER_KEYS,
  isPending,
  normalizeStatus,
  type FilterValue,
  type InboxCounts,
  type InboxTask,
} from "@/app/(main)/inbox/components/inboxShared";
import { InboxTaskList } from "@/app/(main)/inbox/components/InboxTaskList";
import { InboxToolbar } from "@/app/(main)/inbox/components/InboxToolbar";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { resolveEscalationAction } from "@/lib/server-actions";

interface InboxClientProps {
  items: InboxTask[];
  error: string | null;
}

export function InboxClient({ items, error }: InboxClientProps) {
  const router = useRouter();
  const t = useTranslations("InboxPage");
  const [filter, setFilter] = useQueryState(
    "filter",
    parseAsStringLiteral(FILTER_KEYS).withDefault("all")
  );
  const [isCompactLayout, setIsCompactLayout] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [resolved, setResolved] = useState<
    Record<string, "completed" | "failed">
  >({});
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

  const counts = useMemo<InboxCounts>(() => {
    const next = { all: items.length, pending: 0, completed: 0, failed: 0 };
    for (const task of items) next[normalizeStatus(effectiveStatus(task))]++;
    return next;
  }, [items, effectiveStatus]);

  const visible = useMemo(() => {
    return items.filter((task) =>
      filter === "all"
        ? true
        : normalizeStatus(effectiveStatus(task)) === filter
    );
  }, [items, filter, effectiveStatus]);

  const selected =
    visible.find((task) => String(task.id) === selectedId) ?? null;
  // Keep the reading surface in sync with an optimistic resolve so the action
  // footer never offers controls for a task that has already been handled.
  const selectedWithEffectiveStatus = selected
    ? { ...selected, status: effectiveStatus(selected) }
    : null;
  const pendingTasks = items.filter(
    (task) => isPending(effectiveStatus(task)) && task.escalation_id
  );
  const anyChecked = checked.size > 0;

  function changeFilter(next: FilterValue) {
    setFilter(next);
    setChecked(new Set());
    setSelectedId(null);
  }

  // Jump to the first task still waiting on a decision; a filter that hides
  // it (completed / failed) switches to the approval queue first.
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

  async function resolveOne(task: InboxTask, approved: boolean) {
    const id = String(task.id);

    if (!task.escalation_id) {
      router.push(`/tasks/${id}`);
      return;
    }

    if (selectedId === id) {
      const next = visible.find((item) => String(item.id) !== id);
      setSelectedId(next ? String(next.id) : null);
    }

    setResolved((prev) => ({
      ...prev,
      [id]: approved ? "completed" : "failed",
    }));
    setChecked((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
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
      setResolved((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  }

  async function resolveMany(tasks: InboxTask[], approved: boolean) {
    const targets = tasks.filter(
      (task) => isPending(effectiveStatus(task)) && task.escalation_id
    );
    if (!targets.length) return;

    setResolved((prev) => {
      const next = { ...prev };
      for (const task of targets) {
        next[String(task.id)] = approved ? "completed" : "failed";
      }
      return next;
    });
    setChecked(new Set());
    setSelectedId(null);

    try {
      await Promise.all(
        targets.map((task) =>
          resolveEscalationAction(
            task.agent_id,
            String(task.id),
            task.escalation_id as string,
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

  const approveAll =
    filter === "pending" && pendingTasks.length > 0 ? (
      <button
        onClick={() => resolveMany(pendingTasks, true)}
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
        <div className="flex flex-1 items-center justify-center text-sm text-red-500">
          {error}
        </div>
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
              className="flex h-full w-full max-w-none flex-col p-0 sm:max-w-none lg:hidden [&>button]:hidden"
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
                onApprove={() =>
                  resolveMany(
                    items.filter((task) => checked.has(String(task.id))),
                    true
                  )
                }
                onReject={() =>
                  resolveMany(
                    items.filter((task) => checked.has(String(task.id))),
                    false
                  )
                }
                onClear={() => setChecked(new Set())}
              />
            )}

            <div className="min-h-0 flex-1 overflow-y-auto">
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
                onResolve={resolveOne}
              />
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
    </ContentBlock>
  );
}

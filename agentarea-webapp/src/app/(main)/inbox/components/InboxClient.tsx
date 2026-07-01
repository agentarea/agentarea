"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useTransition,
} from "react";
import { Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { InboxClientPanel } from "@/app/(main)/inbox/components/InboxClientPanel";
import { InboxSelectionBar } from "@/app/(main)/inbox/components/InboxSelectionBar";
import { InboxTaskList } from "@/app/(main)/inbox/components/InboxTaskList";
import { InboxToolbar } from "@/app/(main)/inbox/components/InboxToolbar";
import {
  FILTER_KEYS,
  type InboxCounts,
  type InboxTask,
  isPending,
  normalizeStatus,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";
import type { TaskWithAgent } from "@/lib/api";
import { getInboxAction, resolveEscalationAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

interface InboxClientProps {
  initialItems: InboxTask[];
  initialTotal: number;
  pageSize: number;
  error: string | null;
}

export function InboxClient({
  initialItems,
  initialTotal,
  pageSize,
  error,
}: InboxClientProps) {
  const router = useRouter();
  const [items, setItems] = useState<InboxTask[]>(initialItems);
  const [total, setTotal] = useState(initialTotal);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reachedEnd, setReachedEnd] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Refs mirror the paging state so loadMore stays referentially stable and the
  // guard is synchronous. A state-based `loadingMore` guard races: the observer
  // can fire twice before setState commits, launching duplicate fetches and
  // thrashing the layout.
  const pageRef = useRef(1);
  const loadingRef = useRef(false);
  const itemsLenRef = useRef(initialItems.length);
  const totalRef = useRef(initialTotal);
  const reachedEndRef = useRef(false);

  const hasMore = !reachedEnd && items.length < total;
  const [filter, setFilter] = useQueryState(
    "filter",
    parseAsStringLiteral(FILTER_KEYS).withDefault("all")
  );
  const [isCompactLayout, setIsCompactLayout] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [desktopPanelTask, setDesktopPanelTask] = useState<InboxTask | null>(
    null
  );
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [resolved, setResolved] = useState<
    Record<string, "completed" | "failed">
  >({});
  const [, startTransition] = useTransition();

  // A fresh first page arrives after router.refresh() (e.g. resolving an
  // escalation). Reset the accumulated list and pending UI state to match.
  useEffect(() => {
    setItems(initialItems);
    setTotal(initialTotal);
    setLoadingMore(false);
    setReachedEnd(false);
    setResolved({});
    setChecked(new Set());
    pageRef.current = 1;
    loadingRef.current = false;
    itemsLenRef.current = initialItems.length;
    totalRef.current = initialTotal;
    reachedEndRef.current = false;
  }, [initialItems, initialTotal]);

  const loadMore = useCallback(async () => {
    if (
      loadingRef.current ||
      reachedEndRef.current ||
      itemsLenRef.current >= totalRef.current
    ) {
      return;
    }
    loadingRef.current = true;
    setLoadingMore(true);
    try {
      const nextPage = pageRef.current + 1;
      const res = await getInboxAction({
        page: nextPage,
        page_size: pageSize,
      });
      if (res.error) {
        // Stop auto-retrying on error, otherwise the visible sentinel keeps
        // re-triggering into a hot loop.
        reachedEndRef.current = true;
        setReachedEnd(true);
        return;
      }
      const data = res.data as any;
      const newItems = (data?.items ?? []) as InboxTask[];
      pageRef.current = nextPage;
      if (typeof data?.total === "number") {
        totalRef.current = data.total;
        setTotal(data.total);
      }
      setItems((prev) => {
        const seen = new Set(prev.map((task) => String(task.id)));
        const merged = [
          ...prev,
          ...newItems.filter((task) => !seen.has(String(task.id))),
        ];
        // No forward progress (empty page or all duplicates) → stop, or the
        // sentinel stays visible and we loop forever.
        if (merged.length === prev.length) {
          reachedEndRef.current = true;
          setReachedEnd(true);
        }
        itemsLenRef.current = merged.length;
        return merged;
      });
    } finally {
      loadingRef.current = false;
      setLoadingMore(false);
    }
  }, [pageSize]);

  // Re-observe when the list grows so that, if the sentinel is still in view
  // after a page loads, the next page is fetched — one page per cycle. The
  // synchronous loadingRef guard prevents overlap; reachedEnd/hasMore terminate.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) loadMore();
      },
      { root, rootMargin: "200px" }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, loadMore, items.length]);

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

  const selected = visible.find((task) => String(task.id) === selectedId) ?? null;
  const desktopPanelOpen = !isCompactLayout && Boolean(selected);
  const pendingTasks = items.filter(
    (task) => isPending(effectiveStatus(task)) && task.escalation_id
  );
  const anyChecked = checked.size > 0;

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
    setSelectedId(null);
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
        <Check size={14} strokeWidth={2.4} /> Approve all
      </button>
    ) : null;

  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: "Inbox" }], controls: approveAll }}
      subheader={
        <InboxToolbar
          counts={counts}
          filter={filter}
          visibleCount={visible.length}
          onChange={changeFilter}
        />
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
                onClose={() => setSelectedId(null)}
              />
            </SheetContent>
          </Sheet>

          <div
            className={cn(
              "flex min-w-0 flex-1 flex-col overflow-hidden",
              desktopPanelTask && "border-r border-zinc-200 dark:border-zinc-700"
            )}
          >
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

            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
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
              {hasMore && (
                <div
                  ref={sentinelRef}
                  className="flex justify-center py-4"
                  aria-hidden={!loadingMore}
                >
                  {loadingMore && <LoadingSpinner size="sm" />}
                </div>
              )}
            </div>
          </div>

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
                    : "pointer-events-none translate-x-6 opacity-0"
                )}
              >
                <InboxClientPanel
                  task={desktopPanelTask}
                  onResolve={resolveOne}
                  onClose={() => setSelectedId(null)}
                />
              </div>
            )}
          </aside>
        </div>
      )}
    </ContentBlock>
  );
}

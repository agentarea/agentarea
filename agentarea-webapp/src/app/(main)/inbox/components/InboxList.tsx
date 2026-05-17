"use client";

import Link from "next/link";
import { Bot, CheckCircle2, ChevronRight, Circle, Clock, Loader2, XCircle } from "lucide-react";
import { formatDistanceToNowStrict } from "date-fns";
import EmptyState from "@/components/EmptyState";
import type { TaskWithAgent } from "@/lib/api";

interface InboxListProps {
  items: TaskWithAgent[];
  filter: "all" | "pending" | "completed" | "failed";
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "pending":
      return <Clock className="h-6 w-6 text-amber-500 shrink-0" />;
    case "completed":
    case "success":
      return <CheckCircle2 className="h-6 w-6 text-emerald-500 shrink-0" />;
    case "failed":
    case "error":
      return <XCircle className="h-6 w-6 text-red-500 shrink-0" />;
    case "running":
      return <Loader2 className="h-6 w-6 text-blue-500 animate-spin shrink-0" />;
    default:
      return <Circle className="h-6 w-6 text-muted-foreground shrink-0" />;
  }
}

function formatRelative(dateStr: string): string {
  try {
    return formatDistanceToNowStrict(new Date(dateStr), { addSuffix: true });
  } catch {
    return "";
  }
}

function emptyTitle(filter: InboxListProps["filter"]): string {
  switch (filter) {
    case "pending":
      return "No items awaiting approval";
    case "completed":
      return "No completed tasks";
    case "failed":
      return "No failed tasks";
    default:
      return "No items in inbox";
  }
}

function emptyDescription(filter: InboxListProps["filter"]): string {
  switch (filter) {
    case "pending":
      return "Tasks waiting for your approval will appear here.";
    case "completed":
      return "Successfully completed tasks will appear here.";
    case "failed":
      return "Tasks that encountered errors will appear here.";
    default:
      return "Tasks waiting for approval, completed tasks, and failed tasks will appear here.";
  }
}

export function InboxList({ items, filter }: InboxListProps) {
  if (items.length === 0) {
    return (
      <EmptyState
        title={emptyTitle(filter)}
        description={emptyDescription(filter)}
        iconsType="tasks"
      />
    );
  }

  return (
    <div className="divide-y">
      {items.map((task) => (
        <Link
          key={task.id}
          href={`/tasks/${task.id}`}
          className="flex items-center gap-3 px-3 py-2 border-b last:border-b-0 hover:bg-muted/40 transition-colors"
        >
          <StatusIcon status={task.status} />

          <div className="flex-1 min-w-0">
            <p className="font-medium text-sm line-clamp-1">
              {task.description || "Untitled task"}
            </p>
            <div className="flex items-center gap-2 text-[11px] text-muted-foreground mt-0.5">
              <Bot className="h-3 w-3 shrink-0" />
              <span>{(task as any).agent_name || "Unknown agent"}</span>
              <span>·</span>
              <span>{task.created_at ? formatRelative(task.created_at) : ""}</span>
              {(task as any).total_cost != null && (task as any).total_cost > 0 && (
                <>
                  <span>·</span>
                  <span>${Number((task as any).total_cost).toFixed(4)}</span>
                </>
              )}
            </div>
          </div>

          <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />
        </Link>
      ))}
    </div>
  );
}

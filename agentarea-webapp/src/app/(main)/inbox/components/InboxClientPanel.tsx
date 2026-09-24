"use client";

import { useLocale } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Check,
  ChevronRight,
  Clock,
  ExternalLink,
  Inbox as InboxIcon,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import {
  fmtCost,
  formatRelative,
  isPending,
  type InboxTask,
} from "@/app/(main)/inbox/components/inboxShared";
import { AgentAvatar } from "@/components/AgentAvatar";
import { TaskConversation } from "@/components/Chat/TaskConversation";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import { useCurrency } from "@/hooks/useCurrency";
import { EscalationArguments } from "./EscalationArguments";
import { extractInboxResult } from "./inboxResult";
import { InboxResultMessage } from "./InboxResultMessage";

interface InboxClientPanelProps {
  task: InboxTask | null;
  onResolve: (task: InboxTask, approved: boolean) => void;
  onClose: () => void;
}

export function InboxClientPanel({
  task,
  onResolve,
  onClose,
}: InboxClientPanelProps) {
  const router = useRouter();
  const locale = useLocale();
  const { currency } = useCurrency();

  if (!task) {
    return (
      <div className="flex h-full flex-1 flex-col items-center justify-center px-10 text-center text-sm text-muted-foreground">
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
  const agentName = task.agent_name || "Unknown agent";
  const hasResult = extractInboxResult(task.result).kind !== "empty";
  const failureText = task.error || task.failure_reason;

  // Shown only when the transcript carries no assistant answer of its own —
  // an approval still waiting to run, or a task whose output lives in the
  // record rather than the event stream.
  const resultFallback = (
    <>
      <InboxResultMessage
        id={String(task.id)}
        agentId={task.agent_id}
        result={task.result}
        agentName={agentName}
        timestamp={task.created_at}
      />
      {!hasResult && failureText && (
        <p className="max-w-3xl whitespace-pre-wrap break-words text-sm leading-relaxed text-red-600 dark:text-red-400 [overflow-wrap:anywhere]">
          {failureText}
        </p>
      )}
      {!hasResult && !failureText && (
        <p className="text-sm text-muted-foreground">
          {pend
            ? "Output will be available after the action runs."
            : "No output was returned for this task."}
        </p>
      )}
      {hasResult && failureText && (
        <p className="mt-4 break-words text-sm leading-relaxed text-red-600 dark:text-red-400 [overflow-wrap:anywhere]">
          {failureText}
        </p>
      )}
    </>
  );

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col bg-background">
      <header className="shrink-0 border-b border-border px-5 py-3 sm:px-6">
        <div className="flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
            <AgentAvatar
              agent={{ id: task.agent_id || agentName, name: agentName }}
              size="xs"
            />
            <span className="truncate font-medium text-foreground/80">
              {agentName}
            </span>
            <ChevronRight size={13} aria-hidden />
            <span className="shrink-0">Inbox review</span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <Link
              href={`/tasks/${task.id}`}
              className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-[11.5px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ExternalLink size={12} aria-hidden />
              <span className="hidden sm:inline">Open chat</span>
              <span className="sr-only sm:hidden">Open chat</span>
            </Link>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              onClick={onClose}
              aria-label="Close details panel"
              className="h-7 w-7 p-0"
            >
              <X size={14} strokeWidth={2} />
            </Button>
          </div>
        </div>

        {/* The request itself opens the transcript as a user message, exactly
            as in the chat, so the header does not repeat it. */}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <span className="inline-flex items-center rounded-full border border-border bg-muted/40 px-2.5 py-1">
            <TaskStatus status={status} />
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-muted-foreground">
            <Clock size={13} aria-hidden />
            <span>
              {formatRelative(task.created_at) || "Requested recently"}
            </span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 font-mono text-muted-foreground">
            <Wallet size={13} aria-hidden />
            <span>{fmtCost(task.total_cost, currency, locale)}</span>
          </span>
        </div>
      </header>

      {pend && (
        <div className="shrink-0 border-b border-amber-500/25 bg-amber-500/10 px-5 py-2.5 text-sm leading-relaxed text-foreground/85 sm:px-6">
          <div className="flex items-start gap-2.5">
            <Zap
              size={17}
              className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400"
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <p>
                Approving will let the agent run{" "}
                <b className="font-semibold text-foreground">
                  {task.escalation_tool_name || "the requested action"}
                </b>
                .
              </p>
              {task.escalation_id && (
                <EscalationArguments
                  agentId={task.agent_id}
                  taskId={String(task.id)}
                  escalationId={task.escalation_id}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Same transcript and composer as /tasks/[id]: read what happened and
          answer without leaving the inbox. Keyed so switching tasks resets the
          event stream instead of folding two tasks into one conversation. */}
      <div className="min-h-0 flex-1">
        <TaskConversation
          key={String(task.id)}
          task={{
            id: String(task.id),
            agent_id: task.agent_id,
            description: task.description,
            agent_name: task.agent_name,
            status,
            created_at: task.created_at,
          }}
          currentStatus={status}
          fallback={resultFallback}
          onRefresh={() => router.refresh()}
        />
      </div>

      {pend && (
        <footer className="shrink-0 border-t border-border bg-background px-5 py-3.5 sm:px-6">
          <div className="flex gap-2.5 sm:justify-end">
            <button
              onClick={() => onResolve(task, false)}
              className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-4 text-[13px] font-semibold text-red-600 transition hover:border-red-500 hover:bg-red-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex-none"
            >
              <X size={16} strokeWidth={2} aria-hidden />
              Reject
            </button>
            <button
              onClick={() => onResolve(task, true)}
              className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-4 text-[13px] font-semibold text-white shadow-sm transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex-none"
            >
              <Check size={16} strokeWidth={2.2} aria-hidden />
              Approve
            </button>
          </div>
        </footer>
      )}
    </div>
  );
}

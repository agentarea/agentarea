"use client";

import Link from "next/link";
import { formatDistanceToNowStrict } from "date-fns";
import {
  Bot,
  Check,
  Clock,
  ExternalLink,
  Inbox as InboxIcon,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { TaskWithAgent } from "@/lib/api";
import { getInboxStatusPresentation } from "@/lib/status";

const STATUS_LABEL: Record<string, string> = {
  pending: "Needs approval",
  completed: "Completed",
  failed: "Failed",
};

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

interface InboxClientPanelProps {
  task: TaskWithAgent | null;
  onResolve: (task: TaskWithAgent, approved: boolean) => void;
  onClose: () => void;
}

export function InboxClientPanel({
  task,
  onResolve,
  onClose,
}: InboxClientPanelProps) {
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
  const agentName = task.agent_name || "Unknown agent";
  const result = task.result;
  const resultText =
    typeof result === "string"
      ? result
      : result && Object.keys(result).length
        ? JSON.stringify(result, null, 2)
        : null;

  return (
    <>
      <div className="relative flex-1 px-5 pt-5">
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={onClose}
          aria-label="Close details panel"
          className="absolute right-3 top-3"
        >
          <X size={14} strokeWidth={2} />
        </Button>

        <StatusIndicator
          size="sm"
          tone={presentation.tone}
          pulse={presentation.pulse}
          className="mb-3 whitespace-nowrap pr-12"
        >
          {presentation.label}
        </StatusIndicator>

        <div className="mb-3.5 flex items-start justify-between gap-2">
          <h2 className="pr-4 text-[19px] font-semibold leading-tight tracking-tight">
            {task.description || "Untitled task"}
          </h2>
          <Link
            href={`/tasks/${task.id}`}
            className="mt-0.5 shrink-0 inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11.5px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
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
          <div className="text-right font-mono">{fmtCost(task.total_cost)}</div>
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

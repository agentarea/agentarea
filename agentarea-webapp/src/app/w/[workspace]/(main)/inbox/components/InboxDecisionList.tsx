"use client";

import type { ReactNode } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import {
  formatRelative,
  type InboxDecision,
} from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import { AgentAvatar } from "@/components/AgentAvatar";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";

interface InboxDecisionListProps {
  decisions: InboxDecision[];
  error: string | null;
  /** Rendered when no decision has been recorded yet. */
  empty: ReactNode;
}

/** Answered approvals, newest first: what was decided, by whom, and when. */
export function InboxDecisionList({
  decisions,
  error,
  empty,
}: InboxDecisionListProps) {
  const t = useTranslations("InboxPage");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });

  if (error) {
    return <RetryEmptyState title={t("decisions.loadFailed")} description={error} />;
  }
  if (decisions.length === 0) return <>{empty}</>;

  return (
    <>
      {decisions.map((decision) => {
        const agentName = decision.agent_name || t("row.unknownAgent");
        const outcome =
          decision.approved === true
            ? { kind: "done" as const, label: t("decisions.approved") }
            : decision.approved === false
              ? { kind: "cancelled" as const, label: t("decisions.rejected") }
              : { kind: "done" as const, label: t("decisions.resolved") };
        const decider = decision.decided_by_name || decision.decided_by;
        return (
          <Link
            key={decision.escalation_id || `${decision.task_id}-${decision.decided_at}`}
            href={`/tasks/${decision.task_id}`}
            className="block"
          >
            <InteractiveListRow
              contentClassName="gap-3"
              start={
                <AgentAvatar
                  agent={{
                    id: decision.agent_id || agentName,
                    name: agentName,
                  }}
                />
              }
              endClassName="flex-col items-end gap-1"
              end={
                <>
                  <StatusIndicator kind={outcome.kind} size="sm">
                    {outcome.label}
                  </StatusIndicator>
                  <span className="whitespace-nowrap text-[11.5px] text-muted-foreground">
                    {formatRelative(format, now, decision.decided_at)}
                  </span>
                </>
              }
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-foreground">
                  {decision.task_description || t("row.untitled")}
                </p>
                <p className="mt-0.5 truncate text-[12px] text-muted-foreground">
                  {[
                    agentName,
                    decision.tool_name
                      ? t("row.request", { tool: decision.tool_name })
                      : null,
                    decider ? t("decisions.by", { name: decider }) : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {decision.comment && (
                  <p className="mt-0.5 truncate text-[12px] italic text-foreground/70">
                    {t("decisions.comment", { comment: decision.comment })}
                  </p>
                )}
              </div>
            </InteractiveListRow>
          </Link>
        );
      })}
    </>
  );
}

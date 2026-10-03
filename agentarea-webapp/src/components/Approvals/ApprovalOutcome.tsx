"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { resolvePrincipalNamesAction } from "./actions";

interface ApprovalOutcomeProps {
  approved: boolean | null;
  toolName: string | null;
  /** Principal id of whoever decided. */
  decidedBy: string | null;
  decidedAt: Date | null;
  comment: string | null;
}

/**
 * A recorded approval decision: the outcome, who made it and when, and the
 * comment that went with it.
 */
export function ApprovalOutcome({
  approved,
  toolName,
  decidedBy,
  decidedAt,
  comment,
}: ApprovalOutcomeProps) {
  const t = useTranslations("Approvals");
  const format = useFormatter();
  const [deciderName, setDeciderName] = useState<string | null>(null);

  useEffect(() => {
    if (!decidedBy) return;
    let cancelled = false;
    resolvePrincipalNamesAction([decidedBy])
      .then((result) => {
        if (!cancelled) setDeciderName(result.data[decidedBy] ?? null);
      })
      .catch((error: unknown) => {
        console.error("Failed to resolve the approver's name", error);
      });
    return () => {
      cancelled = true;
    };
  }, [decidedBy]);

  const outcome =
    approved === true
      ? t("approved")
      : approved === false
        ? t("rejected")
        : t("resolved");
  const decider = deciderName || decidedBy;
  const when = decidedAt
    ? format.dateTime(decidedAt, { dateStyle: "medium", timeStyle: "short" })
    : null;

  return (
    <div className="space-y-1 rounded-md px-1 py-0.5 text-[13px] leading-5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
        <StatusIndicator kind={approved === false ? "cancelled" : "done"}>
          {toolName ? t("outcomeForTool", { outcome, tool: toolName }) : outcome}
        </StatusIndicator>
        {(decider || when) && (
          <span className="text-muted-foreground">
            {decider && when
              ? t("decidedByAt", { name: decider, time: when })
              : decider
                ? t("decidedBy", { name: decider })
                : when}
          </span>
        )}
      </div>
      {comment && (
        <p className="pl-6 text-muted-foreground">
          {t("comment", { comment })}
        </p>
      )}
    </div>
  );
}

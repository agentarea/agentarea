"use client";

import { useId, useState, useTransition } from "react";
import type { ReactNode } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import type { ToolCallApprovalResponse } from "@/api/client/types.gen";
import {
  approveButtonClassName,
  rejectButtonClassName,
} from "@/components/Approvals/ApprovalDecisionCard";
import { ApprovalOutcome } from "@/components/Approvals/ApprovalOutcome";
import { ToolArguments } from "@/components/Approvals/EscalationArguments";
import { FocusCard, FocusHeader, FocusStep } from "@/components/FocusCard";
import FormError from "@/components/FormError";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import type { EntityIdentity } from "@/lib/entity-identity";
import { cn } from "@/lib/utils";
import { parseUtcTimestamp } from "@/utils/dateUtils";
import { decideToolCallApprovalAction } from "./actions";

interface Props {
  approval: ToolCallApprovalResponse;
  /** Who asked: the person whose client made the call. */
  requesterName: string;
  workspaceName: string;
  identity: EntityIdentity;
}

export default function ApproveToolCall({
  approval,
  requesterName,
  workspaceName,
  identity,
}: Props) {
  const t = useTranslations("Approvals.link");
  const tApprovals = useTranslations("Approvals");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const router = useWorkspaceRouter();
  const commentId = useId();
  const [comment, setComment] = useState("");
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  async function decide(approved: boolean) {
    setDeciding(approved ? "approve" : "reject");
    setError(null);
    try {
      const result = await decideToolCallApprovalAction(
        approval.id,
        approved,
        comment.trim()
      );
      if (result.error) {
        setError(apiErrorMessage(result, tApprovals("decisionFailed")));
        setDeciding(null);
        return;
      }
      startTransition(() => router.refresh());
    } catch (err) {
      console.error("Failed to decide the tool call approval", err);
      setError(`${tApprovals("decisionFailed")}: ${formatApiError(err)}`);
      setDeciding(null);
    }
  }

  const expiresAt = parseUtcTimestamp(approval.expires_at);
  const lapses =
    expiresAt &&
    (approval.status === "pending" || approval.status === "approved")
      ? format.relativeTime(expiresAt, now)
      : null;
  const outcome = (
    <ApprovalOutcome
      approved={approval.status !== "rejected"}
      toolName={approval.tool}
      decidedBy={approval.decided_by}
      decidedAt={parseUtcTimestamp(approval.decided_at)}
      comment={approval.comment}
    />
  );

  let body: ReactNode;
  if (approval.status === "pending" && approval.can_decide) {
    body = (
      <div className="space-y-4">
        <div className="space-y-1.5">
          <label
            htmlFor={commentId}
            className="text-xs font-medium text-muted-foreground"
          >
            {tApprovals("commentLabel")}
          </label>
          <Textarea
            id={commentId}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder={tApprovals("commentPlaceholder")}
            className="min-h-[56px] bg-background text-sm"
            disabled={Boolean(deciding)}
          />
        </div>
        <div className="flex gap-2.5 sm:justify-end">
          <button
            type="button"
            onClick={() => decide(false)}
            disabled={Boolean(deciding)}
            className={rejectButtonClassName}
          >
            {deciding === "reject" ? (
              <LoadingSpinner size="sm" />
            ) : (
              <X size={16} strokeWidth={2} aria-hidden />
            )}
            {tApprovals("reject")}
          </button>
          <button
            type="button"
            onClick={() => decide(true)}
            disabled={Boolean(deciding)}
            className={approveButtonClassName}
          >
            {deciding === "approve" ? (
              <LoadingSpinner variant="light" size="sm" />
            ) : (
              <Check size={16} strokeWidth={2.2} aria-hidden />
            )}
            {tApprovals("approve")}
          </button>
        </div>
      </div>
    );
  } else if (approval.status === "pending") {
    body = (
      <FocusStep
        kind="attention"
        title={t("waitingTitle")}
        detail={tApprovals("notAnApprover")}
      />
    );
  } else if (approval.status === "approved") {
    body = (
      <div className="space-y-3">
        <FocusStep
          kind="done"
          title={t("doneTitle")}
          detail={t("approvedDetail", { time: lapses ?? "" })}
        />
        {outcome}
      </div>
    );
  } else if (approval.status === "rejected") {
    body = (
      <div className="space-y-3">
        <FocusStep
          kind="cancelled"
          title={t("doneTitle")}
          detail={t("rejectedDetail")}
        />
        {outcome}
      </div>
    );
  } else if (approval.status === "consumed") {
    body = (
      <div className="space-y-3">
        <FocusStep
          kind="done"
          title={t("consumedTitle")}
          detail={t("consumedDetail")}
        />
        {outcome}
      </div>
    );
  } else {
    body = (
      <FocusStep
        kind="off"
        title={t("expiredTitle")}
        detail={t("expiredDetail")}
      />
    );
  }

  return (
    <FocusCard>
      <FocusHeader
        identity={identity}
        title={t("title", {
          tool: approval.tool,
          connector: approval.connector,
        })}
        subtitle={t("workspace", { workspace: workspaceName })}
      />
      <dl className="space-y-3 text-sm">
        <Detail label={t("askedBy")}>
          {approval.client_name
            ? t("askedByVia", {
                name: requesterName,
                client: approval.client_name,
              })
            : t("askedByMcp", { name: requesterName })}
        </Detail>
        <Detail label={t("tool")}>
          <span className="flex flex-wrap items-center gap-2">
            <code className="break-all font-mono text-xs">
              {approval.policy_name}
            </code>
            {approval.hint && (
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                  approval.hint === "destructive"
                    ? "border-red-500/40 text-red-600 dark:text-red-400"
                    : "border-border text-muted-foreground"
                )}
              >
                {approval.hint === "destructive"
                  ? t("hintDestructive")
                  : t("hintReadOnly")}
              </span>
            )}
          </span>
        </Detail>
        <Detail label={t("policy")}>{approval.reason}</Detail>
        {lapses && approval.status === "pending" && (
          <Detail label={t("expires")}>{lapses}</Detail>
        )}
        <Detail label={t("arguments")}>
          {approval.arguments ? (
            <ToolArguments args={approval.arguments} />
          ) : (
            <span className="text-xs text-muted-foreground">
              {t("argumentsHidden")}
            </span>
          )}
        </Detail>
      </dl>
      <div className="space-y-4 border-t border-border pt-4">
        {body}
        {error && <FormError>{error}</FormError>}
      </div>
    </FocusCard>
  );
}

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

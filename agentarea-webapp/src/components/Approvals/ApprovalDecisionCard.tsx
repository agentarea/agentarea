"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import FormError from "@/components/FormError";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { EscalationArguments } from "./EscalationArguments";
import { usePendingEscalation } from "./usePendingEscalation";

export type ApprovalDecisionResult = { error?: unknown } | void;

interface ApprovalDecisionCardProps {
  agentId: string;
  taskId: string;
  escalationId: string;
  toolName?: string | null;
  onDecide: (
    approved: boolean,
    comment: string
  ) => Promise<ApprovalDecisionResult>;
}

export const approveButtonClassName =
  "inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-emerald-600 px-4 text-[13px] font-semibold text-white shadow-sm transition hover:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 sm:flex-none";
export const rejectButtonClassName =
  "inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-border bg-background px-4 text-[13px] font-semibold text-red-600 transition hover:border-red-500 hover:bg-red-500/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 sm:flex-none";

/**
 * The one place a person approves or rejects a tool call: the exact call, an
 * optional comment that travels with the decision, and the two buttons. Used by
 * the task page and the inbox, so both send the same decision the same way.
 */
export function ApprovalDecisionCard({
  agentId,
  taskId,
  escalationId,
  toolName,
  onDecide,
}: ApprovalDecisionCardProps) {
  const t = useTranslations("Approvals");
  const commentId = useId();
  const pending = usePendingEscalation(agentId, taskId, escalationId);
  const [comment, setComment] = useState("");
  const [deciding, setDeciding] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canDecide =
    pending.state === "loaded" && Boolean(pending.escalation) && !deciding;
  const tool =
    toolName ||
    (pending.state === "loaded" ? pending.escalation?.tool_name : null);

  async function decide(approved: boolean) {
    setDeciding(approved ? "approve" : "reject");
    setError(null);
    try {
      const result = await onDecide(approved, comment.trim());
      if (result && result.error) {
        setError(apiErrorMessage(result, t("decisionFailed")));
      }
    } catch (e) {
      console.error("Failed to resolve escalation", e);
      setError(`${t("decisionFailed")}: ${formatApiError(e)}`);
    } finally {
      setDeciding(null);
    }
  }

  return (
    <section
      aria-label={t("cardLabel")}
      className="space-y-3 rounded-xl border border-orange-500/25 bg-orange-500/5 p-3.5 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusIndicator kind="attention" size="sm" className="font-medium">
          {t("required")}
        </StatusIndicator>
      </div>
      <p className="leading-relaxed text-foreground/85">
        {t.rich("willRun", {
          tool: tool || t("requestedAction"),
          b: (chunks) => (
            <b className="font-semibold text-foreground">{chunks}</b>
          ),
        })}
      </p>
      <EscalationArguments pending={pending} />
      {pending.state === "loaded" && pending.escalation && (
        <>
          <div className="space-y-1.5">
            <label
              htmlFor={commentId}
              className="text-xs font-medium text-muted-foreground"
            >
              {t("commentLabel")}
            </label>
            <Textarea
              id={commentId}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              placeholder={t("commentPlaceholder")}
              className="min-h-[56px] bg-background text-sm"
              disabled={Boolean(deciding)}
            />
          </div>
          {error && <FormError>{error}</FormError>}
          <div className="flex gap-2.5 sm:justify-end">
            <button
              type="button"
              onClick={() => decide(false)}
              disabled={!canDecide}
              className={rejectButtonClassName}
            >
              {deciding === "reject" ? (
                <LoadingSpinner size="sm" />
              ) : (
                <X size={16} strokeWidth={2} aria-hidden />
              )}
              {t("reject")}
            </button>
            <button
              type="button"
              onClick={() => decide(true)}
              disabled={!canDecide}
              className={approveButtonClassName}
            >
              {deciding === "approve" ? (
                <LoadingSpinner variant="light" size="sm" />
              ) : (
                <Check size={16} strokeWidth={2.2} aria-hidden />
              )}
              {t("approve")}
            </button>
          </div>
        </>
      )}
    </section>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { PendingEscalationState } from "./usePendingEscalation";

const BLOCK_CLASS =
  "max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-background/70 px-2.5 py-1.5 font-mono text-xs";

/**
 * The arguments of the call awaiting approval: a shell command verbatim, every
 * other argument as JSON. Renders the loading/error/not-an-approver states of
 * `usePendingEscalation` so every approval surface says the same thing.
 */
export function EscalationArguments({
  pending,
}: {
  pending: PendingEscalationState;
}) {
  const t = useTranslations("Approvals");

  if (pending.state === "loading") {
    return (
      <p className="text-xs text-muted-foreground" role="status">
        {t("argumentsLoading")}
      </p>
    );
  }
  if (pending.state === "error") {
    return (
      <StatusIndicator kind="failed" size="sm" className="text-xs">
        {pending.message}
      </StatusIndicator>
    );
  }
  if (!pending.escalation) {
    return (
      <p className="text-xs text-muted-foreground">{t("notAnApprover")}</p>
    );
  }

  const { command, ...rest } = pending.escalation.tool_args;
  const others =
    typeof command === "string" ? rest : pending.escalation.tool_args;
  return (
    <div className="space-y-1.5">
      {typeof command === "string" && (
        <pre className={`${BLOCK_CLASS} text-foreground`}>{command}</pre>
      )}
      {Object.keys(others).length > 0 && (
        <pre className={`${BLOCK_CLASS} text-muted-foreground`}>
          {JSON.stringify(others, null, 2)}
        </pre>
      )}
      {typeof command !== "string" && Object.keys(others).length === 0 && (
        <p className="text-xs text-muted-foreground">{t("noArguments")}</p>
      )}
    </div>
  );
}

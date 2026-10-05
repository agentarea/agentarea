"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { PendingEscalationResponse } from "@/api/client/types.gen";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { listPendingEscalationsAction } from "@/lib/server-actions";

export type PendingEscalationState =
  | { state: "loading" }
  | { state: "error"; message: string }
  /** `escalation` is undefined when the caller is not one of its approvers. */
  | { state: "loaded"; escalation: PendingEscalationResponse | undefined };

/**
 * The exact call awaiting approval. The event stream redacts tool arguments,
 * so they are read from the workflow, which only lists an escalation to
 * someone who may resolve it.
 */
export function usePendingEscalation(
  agentId: string,
  taskId: string,
  escalationId: string
): PendingEscalationState {
  const t = useTranslations("Approvals");
  const [loaded, setLoaded] = useState<PendingEscalationState>({
    state: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    setLoaded({ state: "loading" });
    listPendingEscalationsAction(agentId, taskId)
      .then((result) => {
        if (cancelled) return;
        setLoaded(
          result.error
            ? {
                state: "error",
                message: apiErrorMessage(result, t("argumentsFailed")),
              }
            : {
                state: "loaded",
                escalation: result.data?.find(
                  (item) => item.escalation_id === escalationId
                ),
              }
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        console.error("Failed to load the pending escalation", error);
        setLoaded({
          state: "error",
          message: `${t("argumentsFailed")}: ${formatApiError(error)}`,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, taskId, escalationId, t]);

  return loaded;
}

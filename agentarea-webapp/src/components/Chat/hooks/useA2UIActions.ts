/**
 * Hook for dispatching A2UI user actions back to the running workflow.
 *
 * When a user interacts with an A2UI surface (clicks a button, submits a form),
 * this hook sends the action to the backend via POST /a2ui/action, which signals
 * the Temporal workflow so the agent can respond.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { A2UIAction } from "../types";
import { sendA2UIActionAction } from "./actions";

export interface A2UIActionPayload {
  name: string;
  surface_id: string;
  source_component_id: string;
  context: Record<string, unknown>;
}

export function useA2UIActions(agentId: string, taskId: string | null) {
  const t = useTranslations("Chat.errors");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
  }, [agentId, taskId]);

  const sendAction = useCallback(
    async (payload: A2UIActionPayload) => {
      if (!taskId) return;

      setError(null);
      try {
        const result = await sendA2UIActionAction(agentId, taskId, payload);
        if (result.error) {
          setError(apiErrorMessage(result, t("actionRejected")));
        }
      } catch (err) {
        console.error("A2UI action failed", err);
        setError(`${t("actionRejected")}: ${formatApiError(err)}`);
      }
    },
    [agentId, taskId, t]
  );

  /** Build and send an action from component interaction */
  const dispatchAction = useCallback(
    (
      action: A2UIAction,
      surfaceId: string,
      sourceComponentId: string,
      resolvedContext?: Record<string, unknown>
    ) => {
      if (!action.event) return;

      const payload: A2UIActionPayload = {
        name: action.event.name,
        surface_id: surfaceId,
        source_component_id: sourceComponentId,
        context: resolvedContext ?? {},
      };

      sendAction(payload);
    },
    [sendAction]
  );

  return { sendAction, dispatchAction, error };
}

"use client";

import { useEffect, useState } from "react";
import type { PendingEscalationResponse } from "@/api/client/types.gen";
import { apiErrorMessage } from "@/lib/api-errors";
import { listPendingEscalationsAction } from "@/lib/server-actions";

interface EscalationArgumentsProps {
  agentId: string;
  taskId: string;
  escalationId: string;
}

type Loaded =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "loaded"; escalation: PendingEscalationResponse | undefined };

/**
 * The exact call awaiting approval. The event stream redacts tool arguments,
 * so they are read from the workflow, which only answers someone who may
 * resolve this escalation.
 */
export function EscalationArguments({
  agentId,
  taskId,
  escalationId,
}: EscalationArgumentsProps) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });

  useEffect(() => {
    let cancelled = false;
    setLoaded({ state: "loading" });
    listPendingEscalationsAction(agentId, taskId).then((result) => {
      if (cancelled) return;
      setLoaded(
        result.error
          ? {
              state: "error",
              message: apiErrorMessage(
                result,
                "Could not load the call to approve"
              ),
            }
          : {
              state: "loaded",
              escalation: result.data?.find(
                (item) => item.escalation_id === escalationId
              ),
            }
      );
    });
    return () => {
      cancelled = true;
    };
  }, [agentId, taskId, escalationId]);

  if (loaded.state === "loading") return null;
  if (loaded.state === "error") {
    return <p className="mt-1.5 text-xs text-red-600">{loaded.message}</p>;
  }
  if (!loaded.escalation) {
    return (
      <p className="mt-1.5 text-xs text-muted-foreground">
        This approval is reserved for a designated approver.
      </p>
    );
  }

  const { command, ...rest } = loaded.escalation.tool_args;
  const hasCommand = typeof command === "string";
  const others = hasCommand ? rest : loaded.escalation.tool_args;
  const blockClass =
    "mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-background/70 px-2.5 py-1.5 font-mono text-xs";
  return (
    <>
      {typeof command === "string" && (
        <pre className={`${blockClass} text-foreground`}>{command}</pre>
      )}
      {Object.keys(others).length > 0 && (
        <pre className={`${blockClass} text-muted-foreground`}>
          {JSON.stringify(others, null, 2)}
        </pre>
      )}
    </>
  );
}

import React from "react";
import HumanInputMessage from "@/components/Chat/componets/HumanInputMessage";
import type {
  HumanInputField,
  HumanInputRequestData,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { Part } from "../contract";

interface FormPartProps {
  part: Part;
  disabled?: boolean;
  onSubmit?: (
    inputRequestId: string,
    answers: Record<string, unknown>,
    secrets: Record<string, HumanInputSecretValue>
  ) => void;
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asFields(value: unknown): HumanInputField[] {
  return Array.isArray(value) ? (value as HumanInputField[]) : [];
}

/**
 * Input/approval form. Resolution is not a flag: a later input.response /
 * approval.response supersedes the request at the same partId, so the part's
 * eventType alone tells us whether it is still awaiting a human.
 */
export const FormPart: React.FC<FormPartProps> = ({
  part,
  onSubmit,
  disabled,
}) => {
  const resolved =
    part.eventType === "input.response" ||
    part.eventType === "approval.response";
  const isApproval =
    part.eventType === "approval.request" ||
    part.eventType === "approval.response";

  // A request the run ended without answering can no longer be submitted, and
  // saying so adds nothing to the transcript -- drop it rather than render a
  // form whose submit button would go nowhere.
  if (!resolved && disabled) return null;

  if (!isApproval && typeof part.data.surface_id === "string") {
    return (
      <StatusIndicator
        tone={resolved ? "success" : "warning"}
        pulse={!resolved}
      >
        {resolved ? "Form response received" : "Waiting for form response"}
      </StatusIndicator>
    );
  }

  if (isApproval) {
    if (resolved) {
      const approved = part.data.approved;
      const decision =
        approved === true
          ? "Approved"
          : approved === false
            ? "Rejected"
            : "Resolved";
      const reason = asString(part.data.reason, "Approval request");
      const comment = asString(part.data.deny_comment ?? part.data.comment);
      return (
        <details className="group text-[13px] leading-5">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-1 py-0.5 text-foreground/80 outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <StatusIndicator tone={approved === false ? "warning" : "success"}>
              {decision}
            </StatusIndicator>
            <span className="min-w-0 truncate text-muted-foreground">
              {reason}
            </span>
          </summary>
          <div className="space-y-1 pb-1 pl-3 pt-1 text-muted-foreground">
            <p>{reason}</p>
            {comment && <p>{comment}</p>}
          </div>
        </details>
      );
    }

    return (
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-foreground">
            {asString(part.data.reason, "Approval required")}
          </span>
          <StatusIndicator tone="warning" pulse>
            Approval required
          </StatusIndicator>
        </div>
      </div>
    );
  }

  const data: HumanInputRequestData = {
    id: part.partId,
    timestamp: asString(part.data.timestamp),
    agent_id: asString(part.data.agent_id),
    event_type: part.eventType,
    input_request_id: part.partId,
    question: asString(part.data.question, "Additional information needed"),
    questions: asFields(part.data.questions),
    resolved,
    _onSubmit: onSubmit,
  };

  return <HumanInputMessage data={data} />;
};

export default FormPart;

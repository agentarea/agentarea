import React from "react";
import { useTranslations } from "next-intl";
import { ApprovalOutcome } from "@/components/Approvals/ApprovalOutcome";
import HumanInputMessage from "@/components/Chat/componets/HumanInputMessage";
import type {
  HumanInputField,
  HumanInputRequestData,
  HumanInputSecretValue,
} from "@/components/Chat/types";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type { Part } from "../contract";
import { eventTimestamp } from "../normalize";

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
      <StatusIndicator kind={resolved ? "done" : "attention"}>
        {resolved ? "Form response received" : "Waiting for form response"}
      </StatusIndicator>
    );
  }

  if (isApproval) {
    return <ApprovalPart part={part} resolved={resolved} />;
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

function ApprovalPart({ part, resolved }: { part: Part; resolved: boolean }) {
  const t = useTranslations("Approvals");
  const toolName = asString(part.data.tool_name) || null;

  if (resolved) {
    const approved = part.data.approved;
    return (
      <ApprovalOutcome
        approved={typeof approved === "boolean" ? approved : null}
        toolName={toolName}
        decidedBy={asString(part.data.approved_by) || null}
        decidedAt={eventTimestamp(part.data)}
        comment={asString(part.data.deny_comment ?? part.data.comment) || null}
      />
    );
  }

  // The decision itself is taken in the approval card above the composer;
  // the transcript only marks where the run stopped to ask.
  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <StatusIndicator kind="attention" className="text-sm font-medium">
        {toolName ? t("requiredForTool", { tool: toolName }) : t("required")}
      </StatusIndicator>
    </div>
  );
}

export default FormPart;

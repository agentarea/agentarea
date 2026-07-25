import React from "react";
import type { Part } from "../contract";
import HumanInputMessage from "@/components/Chat/componets/HumanInputMessage";
import { StatusIndicator } from "@/components/ui/status-indicator";
import type {
  HumanInputField,
  HumanInputRequestData,
  HumanInputSecretValue,
} from "@/components/Chat/types";

interface FormPartProps {
  part: Part;
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
export const FormPart: React.FC<FormPartProps> = ({ part, onSubmit }) => {
  const resolved =
    part.eventType === "input.response" ||
    part.eventType === "approval.response";
  const isApproval =
    part.eventType === "approval.request" ||
    part.eventType === "approval.response";

  if (isApproval) {
    return (
      <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-foreground">
            {asString(part.data.reason, "Approval required")}
          </span>
          {resolved ? (
            <StatusIndicator tone="success">Resolved</StatusIndicator>
          ) : (
            <StatusIndicator tone="warning" pulse>
              Approval required
            </StatusIndicator>
          )}
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

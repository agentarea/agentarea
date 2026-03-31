"use client";

// FIXME: ToolCallCompleted after approval should reference escalation_id
// so the UI can merge approval + execution + result into a single entry.

import React, { useState } from "react";
import { ShieldAlert, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface ApprovalRequestData {
  escalation_id: string;
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
  message: string;
  resolved?: boolean;
  approved?: boolean;
  deny_comment?: string;
  _onResolve?: (escalationId: string, approved: boolean, comment: string) => void;
}

interface Props {
  data: ApprovalRequestData;
}

const ApprovalRequestMessage: React.FC<Props> = ({ data }) => {
  const [showDenyForm, setShowDenyForm] = useState(false);
  const [denyComment, setDenyComment] = useState("");
  const [localResolved, setLocalResolved] = useState<{ approved: boolean } | null>(null);

  const handleApprove = async () => {
    setLocalResolved({ approved: true });
    data._onResolve?.(data.escalation_id, true, "");
  };

  const handleDeny = async () => {
    setLocalResolved({ approved: false });
    data._onResolve?.(data.escalation_id, false, denyComment);
  };

  const isResolved = data.resolved || localResolved !== null;
  const wasApproved = data.approved ?? localResolved?.approved;

  return (
    <MessageWrapper type={isResolved ? "tool-result" : "tool-call"}>
      <BaseMessage
        headerLeft={
          <div className="flex items-center gap-2">
            <ShieldAlert className={`h-4 w-4 ${isResolved ? (wasApproved ? "text-green-500" : "text-red-500") : "text-amber-500"}`} />
            <span>{data.tool_name}</span>
          </div>
        }
        headerRight={
          isResolved ? (
            <span className={wasApproved ? "text-green-600" : "text-red-600"}>
              {wasApproved ? "Approved" : "Denied"}
            </span>
          ) : (
            <span className="animate-pulse text-amber-600">Awaiting approval</span>
          )
        }
        collapsed={isResolved}
      >
        <div className="space-y-3">
          {!isResolved && (
            <p className="text-sm text-gray-600 dark:text-gray-300">
              {data.message}
            </p>
          )}

          {!isResolved && Object.keys(data.arguments || {}).length > 0 && (
            <details className="cursor-pointer text-xs text-gray-500">
              <summary className="hover:text-gray-700 dark:hover:text-gray-300">
                Arguments
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-gray-100 p-2 dark:bg-gray-800">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          )}

          {!isResolved && (
            <div className="flex items-start gap-2">
              <Button
                size="sm"
                variant="default"
                onClick={handleApprove}
                className="bg-green-600 hover:bg-green-700"
              >
                <Check className="mr-1 h-3 w-3" />
                Approve
              </Button>

              {!showDenyForm ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowDenyForm(true)}
                  className="border-red-300 text-red-600 hover:bg-red-50"
                >
                  <X className="mr-1 h-3 w-3" />
                  Deny
                </Button>
              ) : (
                <div className="flex flex-1 flex-col gap-2">
                  <Textarea
                    placeholder="Reason for denial (optional)"
                    value={denyComment}
                    onChange={(e) => setDenyComment(e.target.value)}
                    className="min-h-[60px] text-sm"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={handleDeny}
                    >
                      Deny
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowDenyForm(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {isResolved && !wasApproved && data.deny_comment && (
            <p className="text-sm text-red-600">
              Reason: {data.deny_comment}
            </p>
          )}
        </div>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ApprovalRequestMessage;

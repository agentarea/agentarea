"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, ShieldAlert, X } from "lucide-react";
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
  _onResolve?: (
    escalationId: string,
    approved: boolean,
    comment: string
  ) => void;
}

interface Props {
  data: ApprovalRequestData;
}

const ApprovalRequestMessage: React.FC<Props> = ({ data }) => {
  const t = useTranslations("ApprovalRequestMessage");
  const [showDenyForm, setShowDenyForm] = useState(false);
  const [denyComment, setDenyComment] = useState("");
  const [resolving, setResolving] = useState(false);

  const handleApprove = async () => {
    setResolving(true);
    data._onResolve?.(data.escalation_id, true, "");
  };

  const handleDeny = async () => {
    setResolving(true);
    data._onResolve?.(data.escalation_id, false, denyComment);
  };

  const isResolved = data.resolved;

  return (
    <MessageWrapper type="tool-call">
      <BaseMessage
        headerLeft={
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-amber-500" />
            <span>
              {t("approvalRequired")} {data.tool_name}
            </span>
          </div>
        }
        headerRight={
          isResolved ? (
            <span className={data.approved ? "text-green-600" : "text-red-600"}>
              {data.approved ? t("approved") : t("denied")}
            </span>
          ) : (
            <span className="animate-pulse text-amber-600">{t("waiting")}</span>
          )
        }
        collapsed={false}
      >
        <div className="space-y-3">
          <p className="text-sm text-gray-600 dark:text-gray-300">
            {data.message}
          </p>

          {Object.keys(data.arguments || {}).length > 0 && (
            <details className="cursor-pointer text-xs text-gray-500">
              <summary className="hover:text-gray-700 dark:hover:text-gray-300">
                {t("arguments")}
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-gray-100 p-2 dark:bg-gray-800">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          )}

          {!isResolved && !resolving && (
            <div className="flex items-start gap-2">
              <Button
                size="sm"
                variant="default"
                onClick={handleApprove}
                className="bg-green-600 hover:bg-green-700"
              >
                <Check className="mr-1 h-3 w-3" />
                {t("approve")}
              </Button>

              {!showDenyForm ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setShowDenyForm(true)}
                  className="border-red-300 text-red-600 hover:bg-red-50"
                >
                  <X className="mr-1 h-3 w-3" />
                  {t("deny")}
                </Button>
              ) : (
                <div className="flex flex-1 flex-col gap-2">
                  <Textarea
                    placeholder={t("denyReasonPlaceholder")}
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
                      {t("deny")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setShowDenyForm(false)}
                    >
                      {t("cancel")}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}

          {resolving && !isResolved && (
            <p className="animate-pulse text-sm text-gray-500">
              {t("sendingDecision")}
            </p>
          )}

          {isResolved && !data.approved && data.deny_comment && (
            <p className="text-sm text-red-600">
              {t("reason")} {data.deny_comment}
            </p>
          )}
        </div>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ApprovalRequestMessage;

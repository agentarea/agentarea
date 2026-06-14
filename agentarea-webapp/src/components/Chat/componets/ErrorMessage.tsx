"use client";

import React from "react";
import { useTranslations } from "next-intl";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface ErrorData {
  error: string;
  error_type?: string;
  raw_error?: string;
  is_auth_error?: boolean;
  is_rate_limit_error?: boolean;
  is_quota_error?: boolean;
  is_model_error?: boolean;
  is_network_error?: boolean;
  retryable?: boolean;
  tool_name?: string;
  arguments?: Record<string, any>;
}

const ErrorMessage: React.FC<{ data: ErrorData }> = ({ data }) => {
  const t = useTranslations("ErrorMessage");

  return (
    <MessageWrapper type="error">
      <BaseMessage
        collapsed={true}
        headerLeft={
          <span className="text-red-700 dark:text-red-300">
            {data.error_type || t("error")}
          </span>
        }
      >
        {data.error}
        {data.retryable !== undefined && (
          <>
            <br />
            <span
              className={
                data.retryable
                  ? "text-yellow-600 dark:text-yellow-400"
                  : "text-red-600 dark:text-red-400"
              }
            >
              {data.retryable ? t("retryable") : t("nonRetryable")}
            </span>
          </>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ErrorMessage;

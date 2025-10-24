import React from "react";
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
  const getErrorIcon = () => {
    if (data.is_auth_error) return "\ud83d\udd11";
    if (data.is_rate_limit_error) return "\u23f1\ufe0f";
    if (data.is_quota_error) return "\ud83d\udcb3";
    if (data.is_model_error) return "\ud83e\udd16";
    if (data.is_network_error) return "\ud83c\udf10";
    return "\u26a0\ufe0f";
  };

  const getErrorStyles = () => {
    if (data.retryable !== false) {
      return {
        container:
          "bg-yellow-50 dark:bg-yellow-950/30 border-yellow-200 dark:border-yellow-800",
        text: "text-yellow-700 dark:text-yellow-300",
      };
    }
    return {
      container:
        "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800",
      text: "text-red-700 dark:text-red-300",
    };
  };

  return (
    <MessageWrapper type="error">
      <BaseMessage
        collapsed={true}
        headerLeft={
          <span className="">
            {getErrorIcon()}
            <span className="ml-2 text-red-700 dark:text-red-300">
              {data.error_type || "Error"}
            </span>
          </span>
        }
      >
        {data.error}
        <br />
        {data.error_type && <span>Type: {data.error_type}</span>}
        <br />
        {data.retryable !== undefined && (
          <span
            className={
              data.retryable
                ? "text-yellow-600 dark:text-yellow-400"
                : "text-red-600 dark:text-red-400"
            }
          >
            {data.retryable ? "Retryable" : "Non-retryable"}
          </span>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ErrorMessage;

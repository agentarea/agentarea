import React from "react";
import { useTranslations } from "next-intl";
import { Streamdown } from "streamdown";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface ToolResultData {
  tool_name: string;
  result: any;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, any>;
}

const ToolResultMessage: React.FC<{ data: ToolResultData }> = ({ data }) => {
  const t = useTranslations("Chat.Messages");

  const formatResult = (result: any) => {
    if (typeof result === "string") {
      return (
        <Streamdown
          className="prose prose-sm dark:prose-invert max-w-none"
          components={
            {
              think: ({ children }: any) => (
                <div className="text-xs text-gray-400 dark:text-gray-300">
                  {children}
                </div>
              ),
            } as any
          }
        >
          {result}
        </Streamdown>
      );
    }
    return JSON.stringify(result, null, 2);
  };

  const getStatusColor = () => {
    if (data.success === false) {
      return {
        container:
          "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800",
        header: "text-red-700 dark:text-red-300",
        content: "text-red-800 dark:text-red-200",
        icon: "\u274c",
      };
    }
    return {
      container:
        "bg-green-50 dark:bg-green-950/30 border-green-200 dark:border-green-800",
      header: "text-green-700 dark:text-green-300",
      content: "text-green-800 dark:text-green-200",
      icon: "\u2705",
    };
  };

  const colors = getStatusColor();

  return (
    <MessageWrapper type="tool-result">
      <BaseMessage
        headerLeft={<span>{`${t("toolCall")}: ${data.tool_name}`}</span>}
        collapsed={true}
      >
        <div className={`text-sm leading-relaxed ${colors.content}`}>
          {typeof data.result === "string" ? (
            formatResult(data.result)
          ) : (
            <pre className="overflow-x-auto whitespace-pre-wrap">
              {formatResult(data.result)}
            </pre>
          )}
        </div>
        {Object.keys(data.arguments || {}).length > 0 && (
          <div className="border-current/20 mt-3 border-t pt-2">
            <details className="cursor-pointer">
              <summary className={`text-xs ${colors.header} hover:opacity-80`}>
                Arguments
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-black/5 p-2 text-xs dark:bg-white/5">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {data.execution_time && (
          <div
            className={`border-current/20 mt-2 border-t pt-2 text-xs ${colors.header}`}
          >
            Execution time: {data.execution_time}
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ToolResultMessage;

import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Settings } from "lucide-react";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface ToolCallStartedData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
}

const ToolCallStartedMessage: React.FC<{ data: ToolCallStartedData }> = ({
  data,
}) => {
  const [showCalling, setShowCalling] = useState(true);
  const t = useTranslations("Chat.Messages");

  useEffect(() => {
    // Показываем "calling..." постоянно, пока не заменится на результат
  }, [data]);

  return (
    <MessageWrapper type="tool-call">
      <BaseMessage
        headerLeft={`${t("toolCall")}: ${data.tool_name}`}
        headerRight={
          <div className="flex items-center gap-2">
            {showCalling && (
              <Settings
                className="h-4 w-4 text-blue-500"
                style={{
                  animation: "spin 2.5s linear infinite",
                  transformOrigin: "center",
                }}
              />
            )}
            <span className={showCalling ? "animate-pulse text-blue-600" : ""}>
              {showCalling ? `${t("calling")}...` : `${t("processing")}...`}
            </span>
          </div>
        }
        collapsed={true}
      >
        {Object.keys(data.arguments).length > 0 && (
          <div className="mt-2 text-xs text-blue-600 dark:text-blue-400">
            <details className="cursor-pointer">
              <summary className="hover:text-blue-700 dark:hover:text-blue-300">
                Arguments
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-blue-100 p-2 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ToolCallStartedMessage;

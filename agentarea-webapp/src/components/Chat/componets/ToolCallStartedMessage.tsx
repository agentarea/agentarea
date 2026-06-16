import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Settings } from "lucide-react";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";
import { ToolIcon } from "../utils/toolIcon";
import { describeToolCall } from "../utils/describeToolCall";

interface ToolCallStartedData {
  tool_name: string;
  tool_call_id: string;
  arguments: Record<string, any>;
  server_icon?: string;
}

const ToolCallStartedMessage: React.FC<{ data: ToolCallStartedData }> = ({
  data,
}) => {
  const [showCalling] = useState(true);
  const t = useTranslations("Chat.Messages");
  const desc = describeToolCall(data.tool_name, data.arguments);

  useEffect(() => {
    // Показываем "calling..." постоянно, пока не заменится на результат
  }, [data]);

  return (
    <MessageWrapper
      type="tool-call"
      id={data.tool_call_id ? `tc-${data.tool_call_id}` : undefined}
      iconUrl={data.server_icon}
      icon={<ToolIcon name={data.tool_name} className="text-zinc-700 dark:text-zinc-200" />}
    >
      <BaseMessage
        headerLeft={
          <span className="flex items-center gap-1.5">
            <span className="font-medium text-foreground">{desc.text}</span>
            {desc.code && (
              <code className="rounded bg-black/5 px-1 py-0.5 font-mono text-xs text-muted-foreground dark:bg-white/10">
                {desc.code}
              </code>
            )}
          </span>
        }
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

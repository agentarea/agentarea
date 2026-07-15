import React from "react";
import { Streamdown } from "streamdown";
import type { Components } from "streamdown";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";
import { ToolIcon } from "../utils/toolIcon";
import { fileAwareMarkdownComponents, preprocessFileLinks } from "../utils/markdownComponents";
import { describeToolCall } from "../utils/describeToolCall";

interface ToolResultData {
  tool_name: string;
  tool_call_id?: string;
  result: unknown;
  success: boolean;
  execution_time?: string;
  arguments?: Record<string, unknown>;
  server_icon?: string;
}

const ToolResultMessage: React.FC<{ data: ToolResultData }> = ({ data }) => {
  const desc = describeToolCall(data.tool_name, data.arguments);

  const formatResult = (result: unknown) => {
    if (typeof result === "string") {
      return (
        <Streamdown
          className="prose prose-sm dark:prose-invert max-w-none"
          components={fileAwareMarkdownComponents as Components}
          linkSafety={{ enabled: false }}
        >
          {preprocessFileLinks(result)}
        </Streamdown>
      );
    }
    return JSON.stringify(result, null, 2);
  };

  return (
    <MessageWrapper
      type="tool-result"
      id={data.tool_call_id ? `tc-${data.tool_call_id}` : undefined}
      iconUrl={data.server_icon}
      icon={<ToolIcon name={data.tool_name} className="text-muted-foreground" />}
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
            {data.success === false && (
              <span className="text-xs text-muted-foreground">failed</span>
            )}
          </span>
        }
        collapsed={true}
      >
        <div className="text-sm leading-relaxed text-foreground/80">
          {typeof data.result === "string" ? (
            formatResult(data.result)
          ) : (
            <pre className="overflow-x-auto whitespace-pre-wrap">
              {formatResult(data.result)}
            </pre>
          )}
        </div>
        {Object.keys(data.arguments || {}).length > 0 && (
          <div className="mt-3 border-t border-border/60 pt-2">
            <details className="cursor-pointer">
              <summary className="text-xs text-muted-foreground hover:opacity-80">
                Arguments
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-black/5 p-2 text-xs dark:bg-white/5">
                {JSON.stringify(data.arguments, null, 2)}
              </pre>
            </details>
          </div>
        )}
        {data.execution_time && (
          <div className="mt-2 border-t border-border/60 pt-2 text-xs text-muted-foreground">
            Execution time: {data.execution_time}
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default ToolResultMessage;

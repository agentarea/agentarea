import React, { useState } from "react";
import { Streamdown } from "streamdown";
import { formatTimestamp } from "../../../utils/dateUtils";
import { LLMResponseData } from "../types";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

const ThinkingBlock: React.FC<{ content: string }> = ({ content }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="mb-3 rounded-md border border-gray-200 dark:border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-t-md"
      >
        <span
          className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}
        >
          ▶
        </span>
        <span>Thinking</span>
      </button>
      {isExpanded && (
        <div className="px-3 pb-2 text-xs text-gray-500 dark:text-gray-400 whitespace-pre-wrap">
          {content}
        </div>
      )}
    </div>
  );
};

export const LLMResponseMessage: React.FC<{
  data: LLMResponseData;
  agent_name?: string;
}> = ({ data, agent_name }) => {
  return (
    <MessageWrapper>
      <BaseMessage
        headerLeft={agent_name || "Assistant"}
        headerRight={formatTimestamp(data.timestamp)}
      >
        {data.thinking && <ThinkingBlock content={data.thinking} />}
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
          {data.content}
        </Streamdown>
        {data.usage && (
          <div className="mt-3 flex gap-4 border-t border-gray-200 pt-2 text-xs text-gray-500 dark:border-gray-700 dark:text-gray-400">
            <span>Tokens: {data.usage.usage.total_tokens}</span>
            <span>Cost: ${Number(data.usage.cost ?? 0).toFixed(4)}</span>
          </div>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default LLMResponseMessage;

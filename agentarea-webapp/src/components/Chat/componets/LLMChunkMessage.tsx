import React, { useState } from "react";
import { Streamdown } from "streamdown";
import { stripA2UIFromStreamingContent } from "../utils/messageAccumulator";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface LLMChunkData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
  chunk_type?: "text" | "thinking";
  thinking?: string;
}

const ThinkingBlock: React.FC<{ content: string; isStreaming?: boolean }> = ({
  content,
  isStreaming,
}) => {
  const [isExpanded, setIsExpanded] = useState(true);

  return (
    <div className="mb-3 rounded-md border border-gray-200 dark:border-gray-700">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 rounded-t-md"
      >
        <span className={`transition-transform ${isExpanded ? "rotate-90" : ""}`}>
          ▶
        </span>
        <span>
          {isStreaming ? "Thinking..." : "Thinking"}
        </span>
      </button>
      {isExpanded && (
        <div className="px-3 pb-2 text-xs text-gray-500 dark:text-gray-400 whitespace-pre-wrap">
          {content}
        </div>
      )}
    </div>
  );
};

const LLMChunkMessage: React.FC<{
  data: LLMChunkData;
  agent_name?: string;
}> = ({ data, agent_name }) => {
  const isThinkingOnly = data.chunk_type === "thinking" && !data.chunk;
  const hasThinking = !!data.thinking;

  return (
    <MessageWrapper>
      <BaseMessage
        headerLeft={data.is_final ? agent_name || "Assistant" : null}
        headerRight={data.is_final ? null : isThinkingOnly ? "Thinking..." : "Responding..."}
      >
        {hasThinking && (
          <ThinkingBlock
            content={data.thinking!}
            isStreaming={!data.chunk && !data.is_final}
          />
        )}
        {data.chunk && (
          <Streamdown
            parseIncompleteMarkdown
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
            {stripA2UIFromStreamingContent(data.chunk)}
          </Streamdown>
        )}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default LLMChunkMessage;

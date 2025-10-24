import React from "react";
import { Streamdown } from "streamdown";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface LLMChunkData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
}

const LLMChunkMessage: React.FC<{
  data: LLMChunkData;
  agent_name?: string;
}> = ({ data, agent_name }) => {
  return (
    <MessageWrapper>
      <BaseMessage
        headerLeft={data.is_final ? agent_name || "Assistant" : null}
        headerRight={data.is_final ? null : "Thinking..."}
      >
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
          {data.chunk}
        </Streamdown>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default LLMChunkMessage;

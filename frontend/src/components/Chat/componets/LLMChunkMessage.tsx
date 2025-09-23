import React from 'react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';

interface LLMChunkData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
}

const LLMChunkMessage: React.FC<{ data: LLMChunkData, agent_name?: string }> = ({ data, agent_name }) => {
  return (
    <MessageWrapper>
      <BaseMessage headerLeft={data.is_final ? agent_name || "Assistant" : null} headerRight={data.is_final ? null : 'Thinking...'}>
          {data.chunk}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default LLMChunkMessage;

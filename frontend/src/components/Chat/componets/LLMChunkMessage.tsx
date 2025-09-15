import React from 'react';
import BaseMessage from './BaseMessage';
import MessageWrapper from './MessageWrapper';

interface LLMChunkData {
  chunk: string;
  chunk_index: number;
  is_final: boolean;
}

const LLMChunkMessage: React.FC<{ data: LLMChunkData }> = ({ data }) => {
  return (
    <MessageWrapper>
      <BaseMessage headerLeft={data.is_final ? null : null} headerRight={data.is_final ? null : 'Thinking...'}>
          {data.chunk}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default LLMChunkMessage;

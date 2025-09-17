import React from 'react';
import BaseMessage from './BaseMessage';
import { formatTimestamp } from '../../../utils/dateUtils';
import MessageWrapper from './MessageWrapper';

interface AssistantMessageProps {
  id: string;
  content: string;
  timestamp: string;
  agent_id: string;
  agent_name?: string;
}

export const AssistantMessage: React.FC<AssistantMessageProps> = ({ id, content, timestamp, agent_name }) => {
  return (
    <MessageWrapper>
      <BaseMessage headerLeft={agent_name || "Assistant"} headerRight={formatTimestamp(timestamp)}>
        {content}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default AssistantMessage;
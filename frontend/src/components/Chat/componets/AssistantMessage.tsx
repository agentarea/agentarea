import React from 'react';
import BaseMessage from './BaseMessage';
import { formatTimestamp } from '../../../utils/dateUtils';
import MessageWrapper from './MessageWrapper';
import { Streamdown } from 'streamdown';

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
        <Streamdown className="prose prose-sm dark:prose-invert max-w-none" components={{ think: ({ children }: any) => (
          <div className="text-xs text-gray-400 dark:text-gray-300">{children}</div>
        ) } as any}>
          {content}
        </Streamdown>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default AssistantMessage;
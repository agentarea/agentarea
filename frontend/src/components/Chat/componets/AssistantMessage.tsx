import React from "react";
import { Streamdown } from "streamdown";
import { formatTimestamp } from "../../../utils/dateUtils";
import BaseMessage from "./BaseMessage";
import MessageWrapper from "./MessageWrapper";

interface AssistantMessageProps {
  id: string;
  content: string;
  timestamp: string;
  agent_id: string;
  agent_name?: string;
}

export const AssistantMessage: React.FC<AssistantMessageProps> = ({
  id,
  content,
  timestamp,
  agent_name,
}) => {
  return (
    <MessageWrapper>
      <BaseMessage
        headerLeft={agent_name || "Assistant"}
        headerRight={formatTimestamp(timestamp)}
      >
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
          {content}
        </Streamdown>
      </BaseMessage>
    </MessageWrapper>
  );
};

export default AssistantMessage;

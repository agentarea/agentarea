import React from "react";
import { MessageMarkdown } from "@/components/Chat/MessageMarkdown";
import { useFormatTimestamp } from "../../../utils/dateUtils";
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
  id: _id,
  content,
  timestamp,
  agent_name,
}) => {
  const formatTimestamp = useFormatTimestamp();
  return (
    <MessageWrapper>
      <BaseMessage
        headerLeft={agent_name || "Assistant"}
        headerRight={formatTimestamp(timestamp)}
      >
        <MessageMarkdown content={content} />
      </BaseMessage>
    </MessageWrapper>
  );
};

export default AssistantMessage;

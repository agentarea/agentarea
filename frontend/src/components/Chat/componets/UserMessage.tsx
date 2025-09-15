import React from 'react';
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { User } from "lucide-react";
import MessageWrapper from './MessageWrapper';
import BaseMessage from './BaseMessage';
import { formatTimestamp } from '../../../utils/dateUtils';

interface UserMessageProps {
  id: string;
  content: string;
  timestamp: string;
}

export const UserMessage: React.FC<UserMessageProps> = ({ id, content, timestamp }) => {
  return (
    <MessageWrapper type="user">
      <BaseMessage isUser={true} headerLeft={"User"} headerRight={formatTimestamp(new Date().toISOString())}>
        {content}
      </BaseMessage>
    </MessageWrapper>
  );
};

export default UserMessage;
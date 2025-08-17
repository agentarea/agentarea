import React from 'react';
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { User } from "lucide-react";

interface UserMessageProps {
  id: string;
  content: string;
  timestamp: string;
}

export const UserMessage: React.FC<UserMessageProps> = ({ id, content, timestamp }) => {
  return (
    <div key={id} className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-end">
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-primary text-primary-foreground">
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
        <p className="text-xs opacity-70 mt-2">
          {new Date(timestamp).toLocaleTimeString()}
        </p>
      </div>
      <Avatar className="h-8 w-8 border-2 border-muted">
        <AvatarFallback className="bg-muted">
          <User className="h-4 w-4" />
        </AvatarFallback>
      </Avatar>
    </div>
  );
};

export default UserMessage;
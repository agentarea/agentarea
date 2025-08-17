import React from 'react';
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";

interface MessageWrapperProps {
  children: React.ReactNode;
  className?: string;
}

export const MessageWrapper: React.FC<MessageWrapperProps> = ({ children, className = "" }) => {
  return (
    <div className={`flex gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-start ${className}`}>
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%]">
        {children}
      </div>
    </div>
  );
};

export default MessageWrapper;
import React from 'react';
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";

interface AssistantMessageProps {
  id: string;
  content: string;
  timestamp: string;
  agent_id: string;
}

export const AssistantMessage: React.FC<AssistantMessageProps> = ({ id, content, timestamp }) => {
  return (
    <div key={id} className="flex gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-start">
      <Avatar className="h-8 w-8 border-2 border-primary/20">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      <div className="max-w-[80%] rounded-2xl px-4 py-3 shadow-sm transition-all duration-200 hover:shadow-md bg-background border border-border">
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
        <p className="text-xs opacity-70 mt-2">
          {new Date(timestamp).toLocaleTimeString()}
        </p>
      </div>
    </div>
  );
};

export default AssistantMessage;
import React from 'react';
import { motion } from "framer-motion";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot, User, Settings, Check } from "lucide-react";
import { cn } from '@/lib/utils';

interface MessageWrapperProps {
  children: React.ReactNode;
  className?: string;
  type?: "error" | "success" | "assistant" | "user" | "tool-call" | "tool-result" | "info";
}

export const MessageWrapper: React.FC<MessageWrapperProps> = ({ children, className = "", type = "assistant" }) => {
  return (
    <div className={cn(`relative flex items-stretch gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-start`, type === "user" ? "aa-user-message" : "aa-message-wrapper", className)}>
      {
        type !== "user" && (
        <motion.div 
          aria-hidden="true"
          className="aa-dashed self-stretch border-l border-dashed border-zinc-300 dark:border-zinc-700 origin-top absolute h-full left-4 top-4 z-0 pointer-events-none"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        />
      )}

      <Avatar className={cn("h-8 w-8 border relative z-10 bg-white dark:bg-zinc-800", type === "user" ? "border-primary/80 dark:border-accent/80" : "")}>
        <AvatarFallback className={cn(type === "tool-call" ? "bg-zinc-900 dark:bg-zinc-300" : "bg-white")}>
          {type === "error" ? (
            <span className="inline-block h-3 w-3 rounded-full bg-red-700" />
          ) : type === "user" ? (
            <User className="h-4 w-4 text-primary dark:text-accent" />
          ) : type === "tool-call" ? (
            <Settings className="h-4 w-4 text-white dark:text-zinc-900" />
          ) : type === "tool-result" ? (
            <Check className="h-4 w-4 text-green-500" />
          ) : (
            <Bot className="h-4 w-4 text-text" />
          )}
        </AvatarFallback>
      </Avatar>
      
      {children}
    </div>
  );
};

export default MessageWrapper;
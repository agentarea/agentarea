import React from 'react';
import { motion } from "framer-motion";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Bot } from "lucide-react";

interface MessageWrapperProps {
  children: React.ReactNode;
  className?: string;
  type?: "error" | "success" | "assistant" | "info";
}

export const MessageWrapper: React.FC<MessageWrapperProps> = ({ children, className = "", type = "assistant" }) => {
  return (
    <div className={`aa-message-wrapper relative flex items-stretch gap-3 animate-in slide-in-from-bottom-2 duration-300 justify-start  ${className}`}>
      <motion.div 
        aria-hidden="true"
        className="aa-dashed self-stretch border-l border-dashed border-zinc-300 dark:border-zinc-700 origin-top absolute h-full left-4 top-4 z-0 pointer-events-none"
        initial={{ scaleY: 0 }}
        animate={{ scaleY: 1 }}
        transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
      />

      <Avatar className="h-8 w-8 border-2 border-primary/20 relative z-10 bg-white dark:bg-zinc-800">
        <AvatarFallback className="bg-primary/10">
          <Bot className="h-4 w-4 text-primary" />
        </AvatarFallback>
      </Avatar>
      
      {children}
    </div>
  );
};

export default MessageWrapper;
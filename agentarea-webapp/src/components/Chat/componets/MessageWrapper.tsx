import React from "react";
import { Bot, User } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { cn } from "@/lib/utils";

interface MessageWrapperProps {
  children: React.ReactNode;
  className?: string;
  type?:
    | "error"
    | "success"
    | "assistant"
    | "user"
    | "tool-call"
    | "tool-result"
    | "info";
  /** Optional custom icon node (e.g. a per-tool lucide icon). Takes precedence over the default. */
  icon?: React.ReactNode;
  /** DOM id for deep-linking (e.g. scroll-to from the side panel). */
  id?: string;
}

export const MessageWrapper: React.FC<MessageWrapperProps> = ({
  children,
  className = "",
  type = "assistant",
  icon,
  id,
}) => {
  return (
    <div
      id={id}
      className={cn(
        "scroll-mt-20",
        "relative flex items-start gap-2.5",
        type === "user"
          ? "aa-user-message flex-row-reverse justify-start"
          : "aa-message-wrapper justify-start",
        className
      )}
    >
      <Avatar
        className="relative z-10 h-6 w-6 shrink-0 border border-border/60 bg-background"
      >
        <AvatarFallback
          className="bg-muted/50 text-muted-foreground"
        >
          {icon ? (
            icon
          ) : type === "error" ? (
            <StatusIndicator
              kind="failed"
              size="sm"
              aria-label="Error"
              title="Error"
            />
          ) : type === "user" ? (
            <User className="h-3.5 w-3.5" />
          ) : type === "tool-call" ? (
            <StatusIndicator
              kind="running"
              size="sm"
              aria-label="Running"
              title="Running"
            />
          ) : type === "tool-result" ? (
            <StatusIndicator
              kind="done"
              size="sm"
              aria-label="Completed"
              title="Completed"
            />
          ) : (
            <Bot className="h-3.5 w-3.5" />
          )}
        </AvatarFallback>
      </Avatar>

      {children}
    </div>
  );
};

export default MessageWrapper;

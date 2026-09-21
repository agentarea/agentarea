import React from "react";
import Image from "next/image";
import { Bot, User, Wrench } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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
  /** Optional MCP server icon URL. When provided, replaces the default tool icon. */
  iconUrl?: string;
  // FIXME: iconUrl is passed through but the lookup from server_instance_id → icon is not yet
  // implemented. See EventParser.ts ToolCallCompleted case where server_instance_id is available.
  /** Optional custom icon node (e.g. a per-tool lucide icon). Takes precedence over the default. */
  icon?: React.ReactNode;
  /** DOM id for deep-linking (e.g. scroll-to from the side panel). */
  id?: string;
}

export const MessageWrapper: React.FC<MessageWrapperProps> = ({
  children,
  className = "",
  type = "assistant",
  iconUrl,
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
          {iconUrl && (type === "tool-call" || type === "tool-result") ? (
            <Image src={iconUrl} alt="" width={16} height={16} className="h-4 w-4 rounded-sm object-contain" />
          ) : icon ? (
            icon
          ) : type === "error" ? (
            <span className="inline-block h-3 w-3 rounded-full bg-red-700" />
          ) : type === "user" ? (
            <User className="h-3.5 w-3.5" />
          ) : type === "tool-call" ? (
            <Wrench className="h-3.5 w-3.5 animate-pulse motion-reduce:animate-none" />
          ) : type === "tool-result" ? (
            <Wrench className="h-4 w-4 text-green-500" />
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

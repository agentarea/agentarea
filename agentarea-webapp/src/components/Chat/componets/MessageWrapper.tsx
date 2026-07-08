import React from "react";
import Image from "next/image";
import { motion } from "framer-motion";
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
        `relative flex items-stretch justify-start gap-3 duration-300 animate-in slide-in-from-bottom-2`,
        type === "user" ? "aa-user-message" : "aa-message-wrapper",
        className
      )}
    >
      {type !== "user" && (
        <motion.div
          aria-hidden="true"
          className="aa-dashed pointer-events-none absolute left-4 top-4 z-0 h-full origin-top self-stretch border-l border-dashed border-zinc-300 dark:border-zinc-700"
          initial={{ scaleY: 0 }}
          animate={{ scaleY: 1 }}
          transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
        />
      )}

      <Avatar
        className={cn(
          "relative z-10 h-8 w-8 border bg-white dark:bg-zinc-800",
          type === "user" ? "border-primary/80 dark:border-accent/80" : ""
        )}
      >
        <AvatarFallback
          className={cn(
            icon
              ? "bg-white dark:bg-zinc-800"
              : type === "tool-call"
                ? "bg-zinc-900 dark:bg-zinc-300"
                : "bg-white"
          )}
        >
          {iconUrl && (type === "tool-call" || type === "tool-result") ? (
            <Image src={iconUrl} alt="" width={16} height={16} className="h-4 w-4 rounded-sm object-contain" />
          ) : icon ? (
            icon
          ) : type === "error" ? (
            <span className="inline-block h-3 w-3 rounded-full bg-red-700" />
          ) : type === "user" ? (
            <User className="h-4 w-4 text-primary dark:text-accent" />
          ) : type === "tool-call" ? (
            <Wrench className="h-4 w-4 text-white dark:text-zinc-900 animate-pulse" />
          ) : type === "tool-result" ? (
            <Wrench className="h-4 w-4 text-green-500" />
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

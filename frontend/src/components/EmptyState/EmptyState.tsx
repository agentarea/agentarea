"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Ban,
  Blocks,
  Bot,
  BotOff,
  Brain,
  ChevronsLeftRightEllipsis,
  Cpu,
  Link,
  List,
  Network,
  Server,
  Shield,
  Sparkles,
  Unplug,
  Zap,
} from "lucide-react";
import { EmptyState as EmptyStateComponent } from "@/components/ui/empty-state";

type EmptyStateProps = {
  title: string;
  description?: string;
  iconsType?: "404" | "agent" | "llm" | "mcp" | "tasks";
  action?: {
    label: string;
    href?: string;
    onClick?: () => void;
  };
  additionAction?: {
    label: string;
    href?: string;
    onClick?: () => void;
  };
};

export default function EmptyState({
  description,
  title,
  action,
  additionAction,
  iconsType,
}: EmptyStateProps) {
  const router = useRouter();
  const icons = iconsType
    ? iconsType === "404"
      ? [Ban, Unplug, BotOff]
      : iconsType === "agent"
        ? [Bot, Zap, Shield]
        : iconsType === "llm"
          ? [Sparkles, Cpu, Brain]
          : iconsType === "tasks"
            ? [List, Bot, Blocks]
            : iconsType === "mcp"
              ? [Server, Network, Link]
              : [Bot, Blocks, ChevronsLeftRightEllipsis]
    : [Bot, Blocks, ChevronsLeftRightEllipsis];

  return (
    <motion.div
      className="flex w-full items-center justify-center"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <EmptyStateComponent
        className="max-w-auto w-full hover:border-accent/20 hover:bg-white dark:bg-zinc-800 dark:hover:border-white/30 dark:hover:bg-zinc-800"
        title={title}
        description={description || ""}
        icons={icons}
        action={
          action
            ? {
                label: action.label,
                onClick: () =>
                  action.onClick
                    ? action.onClick()
                    : action.href
                      ? router.push(action.href)
                      : undefined,
              }
            : undefined
        }
        additionAction={
          additionAction
            ? {
                label: additionAction.label,
                onClick: () =>
                  additionAction.onClick
                    ? additionAction.onClick()
                    : additionAction.href
                      ? router.push(additionAction.href)
                      : undefined,
              }
            : undefined
        }
      />
    </motion.div>
  );
}

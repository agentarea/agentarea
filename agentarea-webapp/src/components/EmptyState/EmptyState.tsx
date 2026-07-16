"use client";

import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Ban,
  Blocks,
  Bot,
  BotOff,
  Brain,
  CheckCircle2,
  ChevronsLeftRightEllipsis,
  Clock,
  Cpu,
  DollarSign,
  Key,
  Link,
  type LucideIcon,
  List,
  Network,
  Receipt,
  ScrollText,
  Server,
  Shield,
  ShieldCheck,
  Sparkles,
  Timer,
  Unplug,
  Wallet,
  Zap,
} from "lucide-react";
import { EmptyState as EmptyStateComponent } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";

type EmptyStateProps = {
  title: string;
  description?: string;
  icons?: LucideIcon[];
  iconsType?:
    | "404"
    | "agent"
    | "apiKey"
    | "audit"
    | "healthy"
    | "llm"
    | "mcp"
    | "payments"
    | "skills"
    | "tasks"
    | "triggers";
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
  /** Extra classes merged onto the card — e.g. to make it borderless/compact. */
  className?: string;
  /** Tint applied to the emphasized (center / single) icon. */
  accentClassName?: string;
};

export default function EmptyState({
  description,
  title,
  action,
  additionAction,
  icons,
  iconsType,
  className,
  accentClassName,
}: EmptyStateProps) {
  const router = useRouter();
  const resolvedIcons =
    icons ||
    (iconsType
      ? iconsType === "404"
        ? [Ban, Unplug, BotOff]
        : iconsType === "agent"
          ? [Zap, Bot, Shield]
          : iconsType === "apiKey"
            ? [Key, Shield, Zap]
            : iconsType === "llm"
              ? [Sparkles, Cpu, Brain]
              : iconsType === "mcp"
                ? [Server, Network, Link]
                : iconsType === "payments"
                  ? [DollarSign, Wallet, Receipt]
                  : iconsType === "tasks"
                    ? [List, Bot, Blocks]
                    : iconsType === "triggers"
                      ? [Zap, Clock, Timer]
                      : iconsType === "audit"
                        ? [ScrollText, Shield, Clock]
                        : iconsType === "healthy"
                        ? [Shield, CheckCircle2, Sparkles]
                        : iconsType === "skills"
                          ? [Sparkles, Zap, Blocks]
                          : [Bot, Blocks, ChevronsLeftRightEllipsis]
      : [Bot, Blocks, ChevronsLeftRightEllipsis]);

  return (
    <motion.div
      className="flex w-full items-center justify-center"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <EmptyStateComponent
        className={cn(
          "max-w-auto w-full hover:border-accent/20 hover:bg-white dark:bg-zinc-800 dark:hover:border-white/30 dark:hover:bg-zinc-800",
          className
        )}
        title={title}
        description={description || ""}
        icons={resolvedIcons}
        accentClassName={accentClassName}
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

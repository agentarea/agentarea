"use client"

import { EmptyState as EmptyStateComponent } from "@/components/ui/empty-state";
import { Zap, BotOff, Ban, Unplug, Bot, Cpu, Blocks, Server, Network, Link, Shield, ChevronsLeftRightEllipsis, Brain, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
type EmptyStateProps = {
    title: string;
    description?: string;
    iconsType?: "404" | "agent" | "llm" | "mcp";
    action?: {
      label: string
      href?: string
      onClick?: () => void
    }
    additionAction?: {
      label: string
      href?: string
      onClick?: () => void
    }
}

export default function EmptyState({description, title, action, additionAction, iconsType}: EmptyStateProps) {
    const router = useRouter();
    const icons = iconsType 
      ? iconsType === "404" 
        ? [Ban, Unplug, BotOff] 
        : iconsType === "agent" 
          ? [Bot, Zap, Shield] 
          : iconsType === "llm" 
            ? [Sparkles, Cpu, Brain] 
            : iconsType === "mcp"
              ? [Server, Network, Link]
              : [Bot, Blocks, ChevronsLeftRightEllipsis] 
      : [Bot, Blocks, ChevronsLeftRightEllipsis];

    return (
      <motion.div 
        className="flex items-center justify-center w-full "
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
      >
        <EmptyStateComponent
          className="w-full max-w-auto hover:bg-white hover:border-accent/20 dark:bg-zinc-800 dark:hover:bg-zinc-800 dark:hover:border-white/30 "
          title={title}
          description={description || ""}
          icons={icons}
          action={ action ? {
            label: action.label,
            onClick: () => action.onClick ? action.onClick() : action.href ? router.push(action.href) : undefined
          } : undefined}
          additionAction={ additionAction ? {
            label: additionAction.label,
            onClick: () => additionAction.onClick ? additionAction.onClick() : additionAction.href ? router.push(additionAction.href) : undefined
          } : undefined}
        />
      </motion.div>
    );
}
"use client"

import { EmptyState as EmptyStateComponent } from "@/components/ui/empty-state";
import { Zap, BotOff, Ban, Unplug, Bot, Cpu, Blocks, ChevronsLeftRightEllipsis } from "lucide-react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
type EmptyStateProps = {
    title: string;
    description?: string;
    iconsType?: "404" | "agent";
    action?: {
      label: string
      href?: string
      onClick?: () => void
    }
}

export default function EmptyState({description, title, action, iconsType}: EmptyStateProps) {
    const router = useRouter();
    const icons = iconsType 
      ? iconsType === "404" 
        ? [Ban, Unplug, BotOff] 
        : iconsType === "agent" 
          ? [Bot, Zap, Cpu] 
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
          className="w-full max-w-auto hover:bg-white hover:border-accent/20 "
          title={title}
          description={description || ""}
          icons={icons}
          action={ action ? {
            label: action.label,
            onClick: () => action.onClick ? action.onClick() : action.href ? router.push(action.href) : undefined
          } : undefined}
        />
      </motion.div>
    );
}
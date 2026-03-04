"use client";

import { cn } from "@/lib/utils";
import { ReactNode, useState } from "react";
import { motion } from "framer-motion";

export interface TabItem {
  value: string;
  label: ReactNode;
  icon?: ReactNode;
}

interface AnimatedTabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (value: string) => void;
  className?: string;
  layoutId?: string; // To avoid conflicts if multiple tabs exist on page
}

export function AnimatedTabs({
  tabs,
  activeTab,
  onChange,
  className,
  layoutId = "animated-tabs",
}: AnimatedTabsProps) {
  const [hoveredTab, setHoveredTab] = useState<string | null>(null);

  return (
    <div
      className={cn(
        "relative flex w-full items-center gap-1 rounded-md bg-sidebar dark:bg-zinc-900 p-1 text-sm font-medium",
        className
      )}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.value;
        const isHovered = hoveredTab === tab.value;

        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            onMouseEnter={() => setHoveredTab(tab.value)}
            onMouseLeave={() => setHoveredTab(null)}
            className={cn(
              "relative z-10 flex-1 flex items-center justify-center gap-2 rounded-sm py-1.5 px-3 transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isActive
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {isActive && (
              <motion.div
                layoutId={`${layoutId}-active`}
                className="absolute inset-0 rounded-sm bg-white dark:bg-zinc-950 shadow-sm ring-1 ring-black/5 dark:ring-white/10"
                initial={false}
                transition={{
                  type: "spring",
                  stiffness: 300,
                  damping: 30,
                }}
              />
            )}
            
            {!isActive && isHovered && (
              <motion.div
                layoutId={`${layoutId}-hover`}
                className="absolute inset-0 rounded-sm bg-zinc-200/50 dark:bg-zinc-700/50"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            )}

            <span className="relative z-10 flex items-center justify-center gap-2">
              {tab.icon && <span className="flex items-center justify-center">{tab.icon}</span>}
              <span className="truncate">{tab.label}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

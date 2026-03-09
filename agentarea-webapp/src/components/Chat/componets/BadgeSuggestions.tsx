"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { Sparkles, ArrowRight } from "lucide-react";

export interface BadgeSuggestion {
  label: string;
  text: string;
}

interface BadgeSuggestionsProps {
  suggestions: BadgeSuggestion[];
  onBadgeClick: (text: string) => void;
  visible: boolean;
}

export const BadgeSuggestions: React.FC<BadgeSuggestionsProps> = ({
  suggestions,
  onBadgeClick,
  visible,
}) => {
  if (!visible || suggestions.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "grid grid-cols-1 sm:grid-cols-2 gap-3 transition-all duration-700 ease-out",
        "mx-auto w-full max-w-2xl px-4",
        visible
          ? "opacity-100 mt-6"
          : "opacity-0 pointer-events-none max-h-0 overflow-hidden mt-0"
      )}
    >
      {suggestions.map((badge, index) => (
        <button
          key={index}
          type="button"
          onClick={() => onBadgeClick(badge.text)}
          className={cn(
            "group relative flex items-start gap-3 w-full p-4 text-left",
            "bg-white/50 dark:bg-zinc-900/50 backdrop-blur-sm",
            "hover:bg-white dark:hover:bg-zinc-800",
            "border border-zinc-200/60 dark:border-zinc-800",
            "hover:border-primary/20 dark:hover:border-primary/20",
            "rounded-2xl transition-all duration-300 ease-out",
            "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] hover:shadow-[0_8px_20px_-8px_rgba(0,0,0,0.1)]",
            "active:scale-[0.99]"
          )}
        >
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 group-hover:bg-primary/10 dark:group-hover:bg-primary/20 transition-colors">
            <Sparkles className="h-4 w-4" />
          </div>
          
          <div className="flex flex-col gap-0.5 flex-1 min-w-0">
            <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200 group-hover:text-zinc-900 dark:group-hover:text-zinc-50 transition-colors truncate">
              {badge.label}
            </span>
            <span className="text-xs text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors line-clamp-1">
              {badge.text}
            </span>
          </div>

          <div className="mt-1 opacity-0 -translate-x-2 group-hover:opacity-100 group-hover:translate-x-0 transition-all duration-300 text-zinc-400 dark:text-zinc-500">
            <ArrowRight className="h-4 w-4" />
          </div>
        </button>
      ))}
    </div>
  );
};


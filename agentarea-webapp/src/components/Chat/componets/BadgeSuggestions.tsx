"use client";

import React from "react";
import { cn } from "@/lib/utils";

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
        "flex flex-wrap gap-2 justify-center transition-all duration-700 ease-out",
        "mx-auto w-full max-w-3xl",
        visible
          ? "opacity-100 max-h-32 mt-3"
          : "opacity-0 pointer-events-none max-h-0 overflow-hidden mt-0"
      )}
    >
      {suggestions.map((badge, index) => (
        <button
          key={index}
          type="button"
          onClick={() => onBadgeClick(badge.text)}
          className={cn(
            "px-5 py-1.5 text-xs md:text-sm font-medium rounded-full",
            "bg-primary/10 hover:bg-primary/20 dark:bg-accent/30 dark:hover:bg-accent/50",
            "text-primary dark:text-accent",
            "transition-colors duration-200 ease-out",
            "cursor-pointer border border-zinc-200 dark:border-zinc-700"
          )}
        >
          {badge.label}
        </button>
      ))}
    </div>
  );
};


"use client";

import React, { use } from "react";
import Link from "next/link";
import { ArrowRight, Plug, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

function isPromise<T>(value: T[] | Promise<T[]>): value is Promise<T[]> {
  return typeof (value as Promise<T[]>)?.then === "function";
}

export interface BadgeSuggestion {
  label: string;
  text: string;
  /**
   * Set when the chip is something to go and set up rather than something to
   * ask. Typing "connect an MCP server" into the composer would have sent the
   * agent a request it cannot act on.
   */
  href?: string;
  /** The channel's own logo, resolved by the catalog that owns the artwork. */
  iconUrl?: string | null;
}

interface BadgeSuggestionsProps {
  /**
   * Either the chips themselves, or the promise of them. The workplace hands
   * down a promise so the chat is not held behind reads that only decide what
   * the starter chips say.
   */
  suggestions: BadgeSuggestion[] | Promise<BadgeSuggestion[]>;
  onBadgeClick: (text: string) => void;
  visible: boolean;
}

export const BadgeSuggestions: React.FC<BadgeSuggestionsProps> = ({
  suggestions: given,
  onBadgeClick,
  visible,
}) => {
  const suggestions = isPromise(given) ? use(given) : given;

  if (!visible || suggestions.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "grid grid-cols-1 sm:grid-cols-2 gap-3",
        "mx-auto mt-6 w-full max-w-2xl px-4"
      )}
    >
      {suggestions.map((badge, index) => {
        const shell = cn(
          "group relative flex items-start gap-3 w-full p-4 text-left",
          "bg-white/50 dark:bg-zinc-900/50 backdrop-blur-sm",
          "hover:bg-white dark:hover:bg-zinc-800",
          "border border-zinc-200/60 dark:border-zinc-800",
          "hover:border-primary/20 dark:hover:border-primary/20",
          "rounded-2xl transition-all duration-300 ease-out",
          "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] hover:shadow-[0_8px_20px_-8px_rgba(0,0,0,0.1)]",
          "active:scale-[0.99]"
        );
        const Glyph = badge.href ? Plug : Sparkles;
        const body = (
          <>
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-primary/5 text-primary dark:bg-primary/10 group-hover:bg-primary/10 dark:group-hover:bg-primary/20 transition-colors">
              {/* A plain img, like the trigger listing: these URLs come from
                  the catalog, so the set of hosts is not known ahead of time
                  and cannot be declared to next/image. */}
              {badge.iconUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={badge.iconUrl}
                  alt=""
                  aria-hidden="true"
                  className="h-5 w-5 shrink-0 object-contain"
                />
              ) : (
                <Glyph className="h-4 w-4" />
              )}
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
          </>
        );

        return badge.href ? (
          <Link key={index} href={badge.href} className={shell}>
            {body}
          </Link>
        ) : (
          <button
            key={index}
            type="button"
            onClick={() => onBadgeClick(badge.text)}
            className={shell}
          >
            {body}
          </button>
        );
      })}
    </div>
  );
};

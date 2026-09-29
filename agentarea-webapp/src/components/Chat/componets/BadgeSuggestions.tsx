"use client";

import React, { use } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Plug, Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Shared by the list and its skeleton so the two sit in the same place. */
const CONTAINER = "mx-auto w-full max-w-3xl px-4 md:px-6";

/** Each row enters this much after the one above it. */
const STAGGER_MS = 60;

/** Rises into place; skipped for people who asked for less motion. */
const ENTER =
  "animate-in fade-in slide-in-from-bottom-1 fill-mode-both duration-300 ease-out motion-reduce:animate-none";

/** Widths for the placeholder rows, so they do not read as a grid. */
const SKELETON_ROWS = [
  ["w-36", "w-48"],
  ["w-32", "w-44"],
  ["w-24", "w-40"],
  ["w-36", "w-52"],
];

function isPromise<T>(value: T[] | Promise<T[]>): value is Promise<T[]> {
  return typeof (value as Promise<T[]>)?.then === "function";
}

export interface BadgeSuggestion {
  label: string;
  /** One short line beside the label: what picking the row gets you. */
  hint: string;
  /** The prompt put into the composer when the row is picked. */
  text?: string;
  /**
   * Set when the row is something to go and set up rather than something to
   * ask. Typing "connect an MCP server" into the composer would have sent the
   * agent a request it cannot act on.
   */
  href?: string;
  /** The channel's own logo, resolved by the catalog that owns the artwork. */
  iconUrl?: string | null;
}

interface BadgeSuggestionsProps {
  /**
   * Either the rows themselves, or the promise of them. The workplace hands
   * down a promise so the chat is not held behind reads that only decide what
   * the starter rows say.
   */
  suggestions: BadgeSuggestion[] | Promise<BadgeSuggestion[]>;
  onBadgeClick: (text: string) => void;
  visible: boolean;
}

/**
 * Starter rows under an empty composer: a quiet list, one line each, lined up
 * with the composer's edges so it reads as part of it rather than as a grid of
 * cards competing with it.
 */
export const BadgeSuggestions: React.FC<BadgeSuggestionsProps> = ({
  suggestions: given,
  onBadgeClick,
  visible,
}) => {
  const t = useTranslations("Workplace.suggestions");
  const suggestions = isPromise(given) ? use(given) : given;

  if (!visible || suggestions.length === 0) {
    return null;
  }

  return (
    <div className={CONTAINER}>
      <p
        className={cn(
          "px-3 pb-1.5 text-xs text-zinc-400 dark:text-zinc-500",
          ENTER
        )}
      >
        {t("getStarted")}
      </p>
      <ul className="flex flex-col">
        {suggestions.map((badge, index) => {
          const row = cn(
            "group flex w-full min-w-0 items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] leading-5",
            "transition-colors hover:bg-muted/70 dark:hover:bg-zinc-800/80",
            "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          );
          const Glyph = badge.href ? Plug : Sparkles;
          const body = (
            <>
              <span className="flex size-4 shrink-0 items-center justify-center text-zinc-400 transition-colors group-hover:text-foreground dark:text-zinc-500">
                {/* A plain img, like the trigger listing: these URLs come from
                    the catalog, so the set of hosts is not known ahead of time
                    and cannot be declared to next/image. Greyed until hovered
                    so a row of brand colours does not outshout the list. */}
                {badge.iconUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={badge.iconUrl}
                    alt=""
                    aria-hidden="true"
                    className="size-4 object-contain opacity-60 grayscale transition group-hover:opacity-100 group-hover:grayscale-0"
                  />
                ) : (
                  <Glyph className="size-4" strokeWidth={1.75} />
                )}
              </span>
              <span className="shrink-0 font-medium text-foreground/90">
                {badge.label}
              </span>
              <span className="min-w-0 truncate text-xs text-zinc-400 dark:text-zinc-500">
                {badge.hint}
              </span>
            </>
          );

          return (
            <li
              key={index}
              className={ENTER}
              // After the heading, then one by one down the list.
              style={{ animationDelay: `${(index + 1) * STAGGER_MS}ms` }}
            >
              {badge.href ? (
                <Link href={badge.href} className={row}>
                  {body}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => onBadgeClick(badge.text ?? badge.label)}
                  className={row}
                >
                  {body}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

/**
 * Holds the list's place while its rows are still being read, so the centred
 * composer above does not jump when they arrive. Four rows: the most the list
 * shows.
 */
export function BadgeSuggestionsSkeleton() {
  return (
    <div className={CONTAINER} aria-hidden="true">
      <Skeleton className="mx-3 mb-3 h-3 w-20" />
      {SKELETON_ROWS.map(([label, hint], index) => (
        <div key={index} className="flex items-center gap-3 px-3 py-2.5">
          <Skeleton className="size-4 rounded-sm" />
          <Skeleton className={cn("h-3", label)} />
          <Skeleton className={cn("h-2.5", hint)} />
        </div>
      ))}
    </div>
  );
}

import * as React from "react";
import { cn } from "@/lib/utils";

/** Modifier/action glyphs that read better one size up for optical balance. */
const GLYPHS = new Set(["⌘", "⌥", "⇧", "⌃", "↵", "⏎", "⎋"]);

export type KbdProps = {
  /**
   * Keys to render inside a single badge, e.g. ["⌘", "J"] or ["Esc"].
   * Known modifier/action glyphs are bumped slightly for optical balance.
   */
  keys?: string[];
  children?: React.ReactNode;
  className?: string;
};

/**
 * Keyboard shortcut badge, styled like the sidebar "New task" hint.
 * Reuse anywhere a keyboard shortcut needs to be shown.
 */
export function Kbd({ keys, children, className }: KbdProps) {
  return (
    <kbd
      className={cn(
        "pointer-events-none inline-flex h-[18px] select-none items-center gap-0.5 rounded border border-border/60 bg-muted/40 px-1 font-mono text-[10px] font-medium text-muted-foreground/70",
        className
      )}
    >
      {keys
        ? keys.map((key, i) => (
            <span
              key={i}
              className={cn(GLYPHS.has(key) && "text-[11px] leading-none")}
            >
              {key}
            </span>
          ))
        : children}
    </kbd>
  );
}

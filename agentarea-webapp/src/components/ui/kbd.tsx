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
  /**
   * `inverse` is for dark surfaces such as tooltips, which stay dark in both
   * themes; the default muted tones are unreadable there.
   */
  variant?: "default" | "inverse";
};

const VARIANTS = {
  default: "border-border/60 bg-muted/40 text-muted-foreground/70",
  inverse: "border-white/20 bg-white/10 text-white/80",
};

/**
 * Keyboard shortcut badge, styled like the sidebar "New task" hint.
 * Reuse anywhere a keyboard shortcut needs to be shown.
 */
export function Kbd({ keys, children, className, variant = "default" }: KbdProps) {
  return (
    <kbd
      className={cn(
        "pointer-events-none inline-flex h-[18px] select-none items-center gap-0.5 rounded border px-1 font-mono text-[10px] font-medium",
        VARIANTS[variant],
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

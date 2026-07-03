"use client";

import * as React from "react";
import { AlertCircle, ChevronDown } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { cn } from "@/lib/utils";

const COLLAPSED_LINES = 2;

type FormErrorProps = {
  children: React.ReactNode;
  className?: string;
};

/**
 * Form-level error banner (our destructive Alert style).
 *
 * Collapses to {@link COLLAPSED_LINES} lines with a trailing ellipsis. When the
 * content is taller than that a chevron appears; toggling it expands/collapses
 * with a smooth max-height animation. Short errors (≤ 2 lines) render without a
 * chevron and without an ellipsis.
 *
 * A hidden, never-clamped copy of the text is used purely to measure the full
 * height — so the `line-clamp` on the visible copy never corrupts the
 * measurement (and stays correct on resize / reflow).
 */
export default function FormError({ children, className }: FormErrorProps) {
  const measureRef = React.useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = React.useState(false);
  const [overflowing, setOverflowing] = React.useState(false);
  const [collapsedHeight, setCollapsedHeight] = React.useState<number>();
  const [fullHeight, setFullHeight] = React.useState<number>();

  React.useLayoutEffect(() => {
    const el = measureRef.current;
    if (!el) return;

    const measure = () => {
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 20;
      const collapsed = lineHeight * COLLAPSED_LINES;
      const full = el.scrollHeight;
      setCollapsedHeight(collapsed);
      setFullHeight(full);
      const isOverflowing = full > collapsed + 2;
      setOverflowing(isOverflowing);
      if (!isOverflowing) setExpanded(false);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [children]);

  const maxHeight = !overflowing
    ? undefined
    : expanded
      ? fullHeight
      : collapsedHeight;

  return (
    <Alert
      variant="destructive"
      className={cn(
        "relative flex gap-3 border-destructive/30 bg-destructive/5",
        overflowing && "pr-10",
        className
      )}
    >
      {/* Wrapped so Alert's `[&>svg]:absolute` rule doesn't grab the icon. */}
      <span className="mt-0.5 shrink-0">
        <AlertCircle className="h-4 w-4" />
      </span>

      <div className="relative min-w-0 flex-1">
        {/* Hidden measurer — same width, never clamped, gives the true height. */}
        <p
          ref={measureRef}
          aria-hidden="true"
          className="pointer-events-none invisible absolute inset-x-0 top-0 break-words text-xs leading-4"
        >
          {children}
        </p>

        <div
          className="overflow-hidden transition-[max-height] duration-300 ease-in-out"
          style={maxHeight != null ? { maxHeight } : undefined}
        >
          <p
            className={cn(
              "break-words text-xs leading-4 text-destructive",
              overflowing && !expanded && "line-clamp-2"
            )}
          >
            {children}
          </p>
        </div>
      </div>

      {overflowing && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse error" : "Expand error"}
          className="absolute right-2 top-2.5 grid h-6 w-6 place-items-center rounded-md text-destructive/70 transition-colors hover:bg-destructive/10 hover:text-destructive"
        >
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform duration-300",
              expanded && "rotate-180"
            )}
          />
        </button>
      )}
    </Alert>
  );
}

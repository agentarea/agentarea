"use client";

import { useId } from "react";
import { CheckCircle, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

const ICON_BACKGROUND = {
  delete:
    "bg-destructive/30 text-destructive dark:bg-destructive dark:text-zinc-200",
  success:
    "bg-accent/30 text-accent dark:bg-accent-foreground/20 dark:text-accent",
} as const;

const ICON = { delete: Trash2, success: CheckCircle } as const;

const RING_RADII = [47.5, 71.5, 95.5, 119.5, 143.5, 167.5];

/**
 * Round icon at the top of a modal, with concentric rings fading out behind
 * it. Put it first inside `DialogContent` (with `overflow-hidden`).
 */
export function ModalFeaturedIcon({ type }: { type: "delete" | "success" }) {
  const id = useId();
  const maskId = `${id}-mask`;
  const gradientId = `${id}-gradient`;
  const Icon = ICON[type];

  return (
    <div className="relative w-max">
      <div
        data-featured-icon="true"
        className={cn(
          "relative flex size-12 shrink-0 items-center justify-center rounded-full",
          ICON_BACKGROUND[type]
        )}
      >
        <Icon className="h-6 w-6" />
        <svg
          width="336"
          height="336"
          viewBox="0 0 336 336"
          fill="none"
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-zinc-300 dark:text-zinc-500"
        >
          <mask
            id={maskId}
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width="336"
            height="336"
            style={{ maskType: "alpha" }}
          >
            <rect width="336" height="336" fill={`url(#${gradientId})`} />
          </mask>
          <g mask={`url(#${maskId})`}>
            {RING_RADII.map((r) => (
              <circle key={r} cx="168" cy="168" r={r} stroke="currentColor" />
            ))}
          </g>
          <defs>
            <radialGradient
              id={gradientId}
              cx="0"
              cy="0"
              r="1"
              gradientUnits="userSpaceOnUse"
              gradientTransform="translate(168 168) rotate(90) scale(168 168)"
            >
              <stop />
              <stop offset="1" stopOpacity="0" />
            </radialGradient>
          </defs>
        </svg>
      </div>
    </div>
  );
}

"use client";

import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * "Blueprint" sheet used inside dialogs: dashed side rails filled with a
 * fine diagonal hatch (styles live in globals.css as `.conn-bp`). Put a
 * {@link BlueprintDivider} at the top/bottom (and between sections) to get
 * the full-width dashed rule with crop-mark crosses at the rails.
 */
export function BlueprintSheet({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("conn-bp", className)} {...props} />;
}

/** Full-width dashed divider with crop-mark crosses at the side rails. */
export function BlueprintDivider() {
  return (
    <div className="conn-bp-div" aria-hidden>
      <span className="conn-bp-mkp l" />
      <span className="conn-bp-mkp r" />
    </div>
  );
}

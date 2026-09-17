"use client";

import type { ReactNode } from "react";
import { useFileDrop, type FileDropOptions } from "@/hooks/use-file-drop";
import { cn } from "@/lib/utils";

/** A drop surface for the common case: one region, one highlight.
 *
 * Reach for `useFileDrop` directly when the zone is not a plain wrapper —
 * a table row that is itself a drop target, or a surface whose highlight is
 * an overlay rather than a class on the container.
 */
export function FileDropZone({
  children,
  className,
  activeClassName = "ring-2 ring-primary ring-offset-2",
  ...options
}: FileDropOptions & {
  children: ReactNode;
  className?: string;
  activeClassName?: string;
}) {
  const { isDragging, dropProps } = useFileDrop(options);
  return (
    <div
      {...dropProps}
      data-dragging={isDragging || undefined}
      className={cn(className, isDragging && activeClassName)}
    >
      {children}
    </div>
  );
}

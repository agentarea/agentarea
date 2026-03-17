"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export default function InfoPanelValueBox({
  children,
  className,
  mono = false,
}: {
  children: ReactNode;
  className?: string;
  mono?: boolean;
}) {
  return (
    <div
      className={cn(
        "truncate rounded-md border border-border/50 bg-muted/30 p-1.5 text-xs text-foreground",
        mono && "font-mono",
        className
      )}
    >
      {children}
    </div>
  );
}


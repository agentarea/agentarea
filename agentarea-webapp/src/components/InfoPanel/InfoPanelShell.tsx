"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export default function InfoPanelShell({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700",
        className
      )}
    >
      <div className="min-h-full bg-white dark:bg-zinc-800">{children}</div>
    </div>
  );
}


"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";

interface InboxTabsProps {
  active: string;
  counts: {
    all: number;
    pending: number;
    completed: number;
    failed: number;
  };
}

const TABS = [
  { key: "all", label: "All" },
  { key: "pending", label: "Needs approval" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
] as const;

export function InboxTabs({ active, counts }: InboxTabsProps) {
  return (
    <div className="flex items-center gap-1 border-b mb-2">
      {TABS.map((tab) => {
        const count = counts[tab.key];
        const isActive = active === tab.key;
        return (
          <Link
            key={tab.key}
            href={`/inbox?filter=${tab.key}`}
            className={cn(
              "px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap border-b-2 -mb-px",
              isActive
                ? "border-foreground text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground"
            )}
          >
            {count > 0 ? `${tab.label} (${count})` : tab.label}
          </Link>
        );
      })}
    </div>
  );
}

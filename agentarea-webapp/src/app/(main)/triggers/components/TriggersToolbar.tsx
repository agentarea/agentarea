"use client";

import type { ReactNode } from "react";
import SearchInput from "@/components/SearchInput";

interface TriggersToolbarProps {
  /** Server-rendered list/grid view switcher. */
  tabsSlot: ReactNode;
}

/**
 * Triggers toolbar with a persistent search field on the left and display
 * controls on the right across all breakpoints.
 */
export default function TriggersToolbar({
  tabsSlot,
}: TriggersToolbarProps) {
  return (
    <div className="flex h-[42px] shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-4 dark:border-zinc-700 dark:bg-zinc-800 sm:gap-3">
      <div className="min-w-0 flex-1">
        <SearchInput urlParamName="search" urlPath="/triggers" />
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">{tabsSlot}</div>
    </div>
  );
}

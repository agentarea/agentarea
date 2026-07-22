"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Filter } from "lucide-react";
import SearchInput from "@/components/SearchInput";
import { ToolbarButton } from "@/components/ui/toolbar-button";

interface TriggersToolbarProps {
  /** Server-rendered type filter (All / Cron / Webhook) with live counts. */
  filterSlot: ReactNode;
  /** Server-rendered list/grid view switcher. */
  tabsSlot: ReactNode;
  searchPlaceholder: string;
}

/**
 * Triggers toolbar — mirrors the Skills page mechanics.
 *
 * Desktop (sm+): type filter + inline search + view tabs on one row.
 * Mobile: there's no room for a usable inline search, so it collapses behind a
 * "Filter" button that reveals a third row with the search (same button→row
 * pattern the Skills page uses).
 */
export default function TriggersToolbar({
  filterSlot,
  tabsSlot,
  searchPlaceholder,
}: TriggersToolbarProps) {
  const t = useTranslations("TriggersPage.filter");
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Row 2 — toolbar */}
      <div className="flex h-[42px] shrink-0 items-center gap-2 border-b border-zinc-200 bg-white px-4 dark:border-zinc-700 dark:bg-zinc-800 sm:gap-3">
        {/* Type filter — always visible; fills the row on mobile (scrolls if
            cramped), natural width on desktop. */}
        <div className="min-w-0 flex-1 sm:flex-none sm:shrink-0">{filterSlot}</div>

        {/* Search — desktop inline */}
        <div className="hidden min-w-0 flex-1 sm:block">
          <SearchInput
            urlParamName="search"
            urlPath="/triggers"
            placeholder={searchPlaceholder}
          />
        </div>

        {/* Search toggle — mobile only, sits right before the view switcher.
            Label collapses to an icon on the narrowest phones so it never
            crowds the type filter. */}
        <ToolbarButton
          icon={Filter}
          active={open}
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={t("button")}
          className="sm:hidden"
          labelClassName="hidden min-[420px]:inline"
        >
          {t("button")}
        </ToolbarButton>

        {tabsSlot}
      </div>

      {/* Row 3 — mobile collapsible search */}
      {open && (
        <div className="shrink-0 border-b border-zinc-200 bg-white px-4 py-0 sm:hidden dark:border-zinc-700 dark:bg-zinc-800">
          <SearchInput
            urlParamName="search"
            urlPath="/triggers"
            placeholder={searchPlaceholder}
          />
        </div>
      )}
    </>
  );
}

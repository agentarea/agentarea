"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { SlidersHorizontal } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton } from "@/components/ui/toolbar";
import { cn } from "@/lib/utils";

export interface DisplayMenuProps {
  /** Menu body: `MenuSectionLabel` + `MenuRow`s from `@/components/ui/menu-row`. */
  children: ReactNode;
  /** Class for the button label, e.g. to hide it in a narrow container. */
  labelClassName?: string;
  /** Accessible name for cases where the visible label is collapsed. */
  accessibleLabel?: string;
}

/**
 * Linear-style "Display" menu for page subheaders: a toolbar button that opens
 * the grouping / ordering choices for the list below it. Shared by Skills,
 * Members and Automation so the control looks the same everywhere.
 */
export default function DisplayMenu({
  children,
  labelClassName,
  accessibleLabel,
}: DisplayMenuProps) {
  const t = useTranslations("Common");

  return (
    <Popover>
      <PopoverTrigger asChild>
        <ToolbarButton aria-label={accessibleLabel ?? t("display")}>
          <SlidersHorizontal className="h-3.5 w-3.5 text-muted-foreground" />
          {/* Icon-only on a phone, so the subheader keeps room for the rest. */}
          <span className={cn("max-sm:sr-only", labelClassName)}>
            {t("display")}
          </span>
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-52 p-1.5">
        {children}
      </PopoverContent>
    </Popover>
  );
}

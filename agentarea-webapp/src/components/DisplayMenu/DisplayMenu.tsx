"use client";

import type { ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  MenuRow,
  MenuSectionLabel,
  MenuSeparator,
} from "@/components/ui/menu-row";
import { ToolbarButton } from "@/components/ui/toolbar-button";
import { cn } from "@/lib/utils";

export interface DisplayMenuItem {
  key: string;
  icon?: ReactNode;
  label: ReactNode;
  selected?: boolean;
  onSelect?: () => void;
  trailing?: ReactNode;
}

export interface DisplayMenuSection {
  key: string;
  label?: ReactNode;
  items: DisplayMenuItem[];
}

interface DisplayMenuProps {
  label: ReactNode;
  sections: DisplayMenuSection[];
  align?: "start" | "center" | "end";
  contentClassName?: string;
  labelClassName?: string;
}

export default function DisplayMenu({
  label,
  sections,
  align = "end",
  contentClassName = "w-52 p-1.5",
  labelClassName,
}: DisplayMenuProps) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <ToolbarButton
          icon={SlidersHorizontal}
          labelClassName={cn("hidden min-[420px]:inline", labelClassName)}
        >
          {label}
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent align={align} className={contentClassName}>
        {sections.map((section, sectionIndex) => (
          <div key={section.key}>
            {section.label ? (
              <MenuSectionLabel>{section.label}</MenuSectionLabel>
            ) : null}
            {section.items.map((item) => (
              <MenuRow
                key={item.key}
                icon={item.icon}
                label={item.label}
                selected={item.selected}
                onClick={item.onSelect}
                trailing={item.trailing}
              />
            ))}
            {sectionIndex < sections.length - 1 ? <MenuSeparator /> : null}
          </div>
        ))}
      </PopoverContent>
    </Popover>
  );
}

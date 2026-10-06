"use client";

import { Fragment, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { MenuRow, MenuSeparator } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton } from "@/components/ui/toolbar";

export interface ToolbarSelectOption<T extends string = string> {
  value: T;
  label: ReactNode;
  /** Give every option one, at the same size, so the labels line up. */
  icon?: ReactNode;
}

export interface ToolbarSelectProps<T extends string = string> {
  /** Names the choice for screen readers. */
  label: string;
  /** Shown on the trigger when the chosen option has no icon of its own. */
  icon?: ReactNode;
  /** Options in groups; a divider runs between groups. */
  groups: ToolbarSelectOption<T>[][];
  value: T;
  onChange: (value: T) => void;
}

/**
 * Single-choice dropdown for a page subheader — a filter, a period. The toolbar
 * button shows the current choice; the popover lists the options as MenuRows,
 * the same look as DisplayMenu, so the subheader controls read as one set. On a
 * phone the button keeps only its icon, like DisplayMenu.
 */
export default function ToolbarSelect<T extends string>({
  label,
  icon,
  groups,
  value,
  onChange,
}: ToolbarSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const selected = groups.flat().find((option) => option.value === value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <ToolbarButton active={open}>
          {selected?.icon ?? icon}
          <span className="max-sm:sr-only">{selected?.label ?? label}</span>
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground/70" />
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        // As wide as its longest label within bounds; a long list scrolls
        // instead of running off the screen.
        className="max-h-[var(--radix-popover-content-available-height)] w-max min-w-56 max-w-80 overflow-y-auto p-1.5"
        aria-label={label}
      >
        {groups
          .filter((group) => group.length > 0)
          .map((group, index) => (
            <Fragment key={group[0].value}>
              {index > 0 && <MenuSeparator />}
              {group.map((option) => (
                <MenuRow
                  key={option.value}
                  icon={option.icon}
                  label={option.label}
                  selected={option.value === value}
                  onClick={() => {
                    setOpen(false);
                    if (option.value !== value) onChange(option.value);
                  }}
                />
              ))}
            </Fragment>
          ))}
      </PopoverContent>
    </Popover>
  );
}

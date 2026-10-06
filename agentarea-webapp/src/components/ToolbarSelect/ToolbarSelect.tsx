"use client";

import { Fragment, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  MenuRow,
  MenuSectionLabel,
  MenuSeparator,
} from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton } from "@/components/ui/toolbar";
import { cn } from "@/lib/utils";

export interface ToolbarSelectOption<T extends string = string> {
  value: T;
  label: ReactNode;
  /** Give every option one, at the same size, so the labels line up. */
  icon?: ReactNode;
  /** What the button says once this is chosen, when the row's label needs its group to read right. */
  triggerLabel?: ReactNode;
}

/** A run of options; with a label, it is headed by it. */
export type ToolbarSelectGroup<T extends string = string> =
  | ToolbarSelectOption<T>[]
  | {
      label: ReactNode;
      /** The heading's glyph, used when the groups fold. */
      icon?: ReactNode;
      options: ToolbarSelectOption<T>[];
    };

export interface ToolbarSelectProps<T extends string = string> {
  /** Names the choice for screen readers. */
  label: string;
  /** Shown on the trigger when the chosen option has no icon of its own. */
  icon?: ReactNode;
  /** Options in groups; a divider runs between groups, a labelled group gets a heading. */
  groups: ToolbarSelectGroup<T>[];
  value: T;
  onChange: (value: T) => void;
  /**
   * Fold the labelled groups: each heading becomes a row that opens its
   * options, one group at a time, starting with the one holding the choice.
   * For long lists that would otherwise run down the page.
   */
  collapsible?: boolean;
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
  collapsible = false,
}: ToolbarSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const sections = groups
    .map((group) => (Array.isArray(group) ? { options: group } : group))
    .filter((group) => group.options.length > 0);
  const selected = sections
    .flatMap((group) => group.options)
    .find((option) => option.value === value);
  const holdsChoice = (index: number) =>
    sections[index].options.some((option) => option.value === value);
  const [unfolded, setUnfolded] = useState<number | null>(null);
  // A single labelled group has nothing to fold against.
  const folds =
    collapsible && sections.filter((group) => "label" in group).length > 1;

  const toggle = (next: boolean) => {
    setOpen(next);
    if (next) {
      const index = sections.findIndex((_, i) => holdsChoice(i));
      setUnfolded(index >= 0 ? index : null);
    }
  };

  const optionRows = (options: ToolbarSelectOption<T>[]) =>
    options.map((option) => (
      <MenuRow
        key={option.value}
        icon={option.icon}
        label={option.label}
        selected={option.value === value}
        onClick={() => {
          toggle(false);
          if (option.value !== value) onChange(option.value);
        }}
      />
    ));

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <ToolbarButton active={open}>
          {selected?.icon ?? icon}
          <span className="max-sm:sr-only">
            {selected?.triggerLabel ?? selected?.label ?? label}
          </span>
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
        {sections.map((group, index) => {
          const labelled = "label" in group;
          const isOpen = unfolded === index;
          return (
            <Fragment key={group.options[0].value}>
              {/* A heading parts two labelled groups on its own. */}
              {index > 0 && !(labelled && "label" in sections[index - 1]) && (
                <MenuSeparator />
              )}
              {labelled && folds ? (
                <>
                  <MenuRow
                    icon={group.icon}
                    label={group.label}
                    selected={holdsChoice(index)}
                    onClick={() => setUnfolded(isOpen ? null : index)}
                    trailing={
                      <ChevronRight
                        className={cn(
                          "h-3.5 w-3.5 text-muted-foreground/70 transition-transform duration-200 motion-reduce:transition-none",
                          isOpen && "rotate-90"
                        )}
                      />
                    }
                  />
                  {/* Slides open to its natural height; closed, it is out
                      of the tab order. */}
                  <div
                    inert={!isOpen}
                    className={cn(
                      "grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none",
                      isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                    )}
                  >
                    <div className="min-h-0 overflow-hidden pl-3">
                      {optionRows(group.options)}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {labelled && (
                    <MenuSectionLabel>{group.label}</MenuSectionLabel>
                  )}
                  {optionRows(group.options)}
                </>
              )}
            </Fragment>
          );
        })}
      </PopoverContent>
    </Popover>
  );
}

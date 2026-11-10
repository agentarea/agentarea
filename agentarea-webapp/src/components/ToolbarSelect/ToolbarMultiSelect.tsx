"use client";

import { useState, type ReactNode } from "react";
import { Check, ChevronDown } from "lucide-react";
import { MenuRow, MenuSeparator } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ToolbarButton } from "@/components/ui/toolbar";
import type { ToolbarSelectOption } from "./ToolbarSelect";

export interface ToolbarMultiSelectProps<T extends string = string> {
  /** Names the choice for screen readers. */
  label: string;
  /** The row that clears the choice, and what the button says with nothing picked. */
  all: { label: ReactNode; triggerLabel: ReactNode; icon: ReactNode };
  options: ToolbarSelectOption<T>[];
  values: T[];
  onChange: (values: T[]) => void;
  /** What the button says with more than one picked, e.g. "3 sources". */
  countLabel: (count: number) => ReactNode;
}

/**
 * ToolbarSelect for a choice of several: the same button and rows, but a row
 * toggles (a check marks the picked ones) and the popover stays open while you
 * pick. The "all" row clears the choice. The button shows the one picked
 * option, or how many.
 */
export default function ToolbarMultiSelect<T extends string>({
  label,
  all,
  options,
  values,
  onChange,
  countLabel,
}: ToolbarMultiSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const picked = options.filter((option) => values.includes(option.value));
  const only = picked.length === 1 ? picked[0] : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <ToolbarButton active={open} aria-label={label}>
          {only?.icon ?? all.icon}
          <span data-toolbar-label className="max-sm:sr-only">
            {picked.length === 0
              ? all.triggerLabel
              : only
                ? (only.triggerLabel ?? only.label)
                : countLabel(picked.length)}
          </span>
          <ChevronDown
            data-toolbar-chevron
            className="h-3.5 w-3.5 text-muted-foreground/70"
          />
        </ToolbarButton>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="max-h-[var(--radix-popover-content-available-height)] w-max min-w-56 max-w-80 overflow-y-auto p-1.5"
        aria-label={label}
      >
        <ToolbarMultiSelectRows
          all={all}
          options={options}
          values={values}
          onChange={onChange}
        />
      </PopoverContent>
    </Popover>
  );
}

/** The rows alone, for a menu that holds several filters. */
export function ToolbarMultiSelectRows<T extends string>({
  all,
  options,
  values,
  onChange,
}: Pick<
  ToolbarMultiSelectProps<T>,
  "all" | "options" | "values" | "onChange"
>) {
  const toggle = (value: T) =>
    onChange(
      values.includes(value)
        ? values.filter((v) => v !== value)
        : [...values, value]
    );
  return (
    <>
      <MenuRow
        icon={all.icon}
        label={all.label}
        selected={values.length === 0}
        onClick={() => values.length > 0 && onChange([])}
      />
      {options.length > 0 && <MenuSeparator />}
      {options.map((option) => {
        const selected = values.includes(option.value);
        return (
          <MenuRow
            key={option.value}
            icon={option.icon}
            label={option.label}
            selected={selected}
            onClick={() => toggle(option.value)}
            trailing={
              <Check
                aria-hidden="true"
                className={selected ? "h-3.5 w-3.5" : "invisible h-3.5 w-3.5"}
              />
            }
          />
        );
      })}
    </>
  );
}

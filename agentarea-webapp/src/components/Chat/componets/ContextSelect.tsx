"use client";

import React from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export interface ContextSelectOption {
  id: string;
  name: string;
  description?: string | null;
}

interface ContextSelectProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  disabled?: boolean;
  options: ContextSelectOption[];
  onValueChange: (value: string) => void;
  renderTriggerIcon?: (option: ContextSelectOption) => React.ReactNode;
  renderOptionIcon?: (option: ContextSelectOption) => React.ReactNode;
  className?: string;
}

export function ContextSelect({
  icon: Icon,
  label,
  value,
  disabled,
  options,
  onValueChange,
  renderTriggerIcon,
  renderOptionIcon,
  className,
}: ContextSelectProps) {
  const selectedOption = options.find((option) => option.id === value);

  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger
        aria-label={label}
        className={cn(
          "group h-7 w-fit min-w-0 max-w-full rounded-md border border-transparent bg-transparent pl-1.5 pr-1.5 text-left text-xs text-zinc-500 shadow-none sm:max-w-[18rem] lg:max-w-[20rem]",
          "transition-all duration-150 ease-out hover:bg-zinc-100/70 hover:text-zinc-500",
          "hover:rounded-md focus:border-transparent focus:ring-0 focus-visible:ring-0 data-[state=open]:rounded-md data-[state=open]:bg-zinc-100/80 data-[state=open]:text-zinc-500",
          "[&>svg]:ml-2 [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:shrink-0 [&>svg]:text-zinc-400 [&>svg]:opacity-100 group-hover:[&>svg]:text-zinc-400 data-[state=open]:[&>svg]:text-zinc-400",
          "dark:bg-transparent dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-zinc-400 dark:data-[state=open]:bg-zinc-800/80 dark:data-[state=open]:text-zinc-400 dark:[&>svg]:text-zinc-500 dark:group-hover:[&>svg]:text-zinc-500 dark:data-[state=open]:[&>svg]:text-zinc-500",
          className
        )}
      >
        <div className="flex min-w-0 flex-1 flex-nowrap items-center gap-1 overflow-hidden whitespace-nowrap">
          {selectedOption && renderTriggerIcon ? (
            renderTriggerIcon(selectedOption)
          ) : (
            <Icon className="inline-block h-3.5 w-3.5 shrink-0 text-zinc-400 transition-colors duration-150 group-hover:text-zinc-400 dark:text-zinc-500 dark:group-hover:text-zinc-500" />
          )}
          <span className="block min-w-0 flex-1 truncate whitespace-nowrap pb-px text-[13px] font-normal leading-[1.2] text-zinc-400 dark:text-zinc-300">
            {selectedOption?.name ?? label}
          </span>
        </div>
      </SelectTrigger>
      <SelectContent
        position="popper"
        sideOffset={8}
        className={cn(
          "w-[min(13rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] overflow-hidden rounded-md border border-zinc-200/90 bg-white p-1 text-zinc-900 sm:w-auto sm:min-w-[14rem] lg:min-w-[15rem]",
          "shadow-[0_12px_32px_rgba(15,23,42,0.10),0_2px_6px_rgba(15,23,42,0.04)]",
          "dark:border-zinc-800 dark:bg-zinc-950/95 dark:text-zinc-100"
        )}
      >
        {options.map((option) => (
          <SelectItem
            key={option.id}
            value={option.id}
            className={cn(
              "min-h-8 rounded-sm py-1.5 pl-2 pr-8 text-[13px] font-normal text-zinc-800",
              "focus:bg-zinc-100/90 dark:text-zinc-100 dark:focus:bg-zinc-900"
            )}
          >
            <span className="grid w-full min-w-0 grid-cols-[auto,minmax(0,1fr)] items-start gap-x-2">
              {renderOptionIcon ? (
                renderOptionIcon(option)
              ) : (
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500 dark:text-zinc-400" />
              )}
              <span className="flex min-w-0 max-w-full flex-col overflow-hidden">
                <span className="block w-full min-w-0 truncate leading-4">
                  {option.name}
                </span>
                {option.description ? (
                  <span className="block w-full min-w-0 truncate pt-0.5 text-[11px] font-normal leading-4 text-zinc-500 dark:text-zinc-400">
                    {option.description}
                  </span>
                ) : null}
              </span>
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

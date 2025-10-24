"use client";

import * as React from "react";
import { Bot, Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface SelectOption {
  id: string | number;
  label: string;
  description?: string;
  icon?: string;
}

export interface SimpleSelectOption {
  id: string | number;
  label: string;
}

export interface SelectGroup {
  label: string;
  icon?: string;
  options: (SelectOption | SimpleSelectOption)[];
}

interface SearchableSelectProps {
  options: (SelectOption | SimpleSelectOption)[];
  groups?: SelectGroup[];
  value?: string | number;
  onValueChange: (value: string | number) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  emptyMessage?: string | React.ReactNode;
  defaultIcon?: React.ReactNode;
  renderOption?: (option: SelectOption | SimpleSelectOption) => React.ReactNode;
  renderTrigger?: (
    selectedOption: SelectOption | SimpleSelectOption | undefined
  ) => React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function SearchableSelect({
  options,
  groups,
  value,
  onValueChange,
  placeholder = "Search...",
  disabled = false,
  className,
  emptyMessage = "No items found.",
  defaultIcon,
  renderOption,
  renderTrigger,
  open: controlledOpen,
  onOpenChange: setControlledOpen,
}: SearchableSelectProps) {
  const [popoverWidth, setPopoverWidth] = React.useState<string>("auto");
  const [popoverOpen, setPopoverOpen] = React.useState(false);
  const triggerRef = React.useRef<HTMLButtonElement>(null);

  const selectedOption = (() => {
    // Сначала ищем в группах
    if (groups) {
      for (const group of groups) {
        const found = group.options.find((option) => option.id === value);
        if (found) return found;
      }
    }
    // Затем ищем в обычных опциях
    return options.find((option) => option.id === value);
  })();

  // Use controlled state if provided, otherwise use internal state
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : popoverOpen;

  const handlePopoverOpenChange = (open: boolean) => {
    if (isControlled) {
      setControlledOpen?.(open);
    } else {
      setPopoverOpen(open);
    }

    if (open && triggerRef.current) {
      const width = triggerRef.current.offsetWidth;
      setPopoverWidth(`${width}px`);
    }
  };

  const handleOptionChange = (optionId: string | number) => {
    onValueChange(optionId);
    handlePopoverOpenChange(false);
  };

  const renderIcon = (option: SelectOption) => {
    if (option.icon) {
      return (
        <img
          src={option.icon}
          alt={option.label}
          className="h-5 w-5 rounded dark:invert"
          onError={(e) => {
            if (defaultIcon) {
              e.currentTarget.style.display = "none";
            }
          }}
        />
      );
    }

    return defaultIcon || <Bot className="h-5 w-5 text-muted-foreground" />;
  };

  const renderOptionContent = (option: SelectOption | SimpleSelectOption) => (
    <div className="flex items-center gap-3">
      <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
        {"icon" in option && renderIcon(option as SelectOption)}
      </div>
      <div className="flex flex-col items-start">
        <span>{option.label}</span>
        {"description" in option && option.description && (
          <span className="note">{option.description}</span>
        )}
      </div>
    </div>
  );

  const renderDefaultTrigger = (
    selectedOption: SelectOption | SimpleSelectOption | undefined
  ) => {
    if (selectedOption) {
      return renderOptionContent(selectedOption);
    }
    return (
      <div className="flex items-center gap-2">
        <span className="font-normal text-muted-foreground">{placeholder}</span>
      </div>
    );
  };

  const renderDefaultOption = (option: SelectOption | SimpleSelectOption) => {
    const isSelected = option.id === value;
    return (
      <>
        {renderOptionContent(option)}
        <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
          <Check
            className={cn(
              "h-4 w-4 text-accent dark:text-accent-foreground",
              isSelected ? "opacity-100" : "opacity-0"
            )}
          />
        </span>
      </>
    );
  };

  return (
    <Popover open={isOpen} onOpenChange={handlePopoverOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          variant="outline"
          role="combobox"
          className={cn(
            "w-full justify-between rounded-md px-3 text-foreground shadow-none hover:bg-background hover:text-foreground focus:border-primary focus-visible:border-primary focus-visible:ring-0 dark:bg-zinc-900 dark:focus:border-accent-foreground dark:focus-visible:border-accent-foreground",
            className
          )}
          disabled={disabled}
        >
          {renderTrigger
            ? renderTrigger(selectedOption)
            : renderDefaultTrigger(selectedOption)}
          <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-0" style={{ width: popoverWidth }}>
        <Command>
          <CommandInput placeholder={placeholder} />
          <CommandList>
            <CommandEmpty>{emptyMessage}</CommandEmpty>
            {groups ? (
              // Рендерим группы
              groups.map((group, groupIndex) => (
                <CommandGroup key={groupIndex} heading={group.label}>
                  {group.options.map((option) => (
                    <CommandItem
                      key={option.id}
                      value={`${group.label} ${option.label} ${"description" in option && option.description ? option.description : ""}`}
                      onSelect={() => {
                        handleOptionChange(option.id);
                      }}
                    >
                      {renderOption
                        ? renderOption(option)
                        : renderDefaultOption(option)}
                    </CommandItem>
                  ))}
                </CommandGroup>
              ))
            ) : (
              // Рендерим обычные опции
              <CommandGroup>
                {options.map((option) => (
                  <CommandItem
                    key={option.id}
                    value={`${option.label} ${"description" in option && option.description ? option.description : ""}`}
                    onSelect={() => {
                      handleOptionChange(option.id);
                    }}
                  >
                    {renderOption
                      ? renderOption(option)
                      : renderDefaultOption(option)}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

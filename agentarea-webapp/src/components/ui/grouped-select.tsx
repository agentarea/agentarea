"use client";

import * as React from "react";
import { Check, ChevronDown, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface GroupedSelectItem {
  id: string;
  label: string;
  /** A muted line under the label. */
  description?: string;
  icon?: React.ReactNode;
  /** Shown at the row's end, before the check (e.g. a model's tags). */
  end?: React.ReactNode;
  /** Extra text the search matches besides the label and description. */
  searchText?: string;
}

export interface GroupedSelectGroup {
  id: string;
  label: string;
  description?: string;
  icon?: React.ReactNode;
  items: GroupedSelectItem[];
}

export interface GroupedSelectProps {
  groups: GroupedSelectGroup[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  /** Headings over the two panes, e.g. "Configurations" and "Models". */
  groupsTitle: string;
  itemsTitle: string;
  searchPlaceholder: string;
  /** Under the list when the search leaves the picked group empty. */
  noResults: string;
  /** The whole dropdown when there is nothing to pick from at all. */
  emptyMessage?: React.ReactNode;
  /** A "+" beside the groups' heading. */
  onAddGroup?: () => void;
  /**
   * Whether the field names the picked option's group under it. A model's
   * configuration says how it runs; a trigger type's kind says nothing more.
   */
  showGroupInValue?: boolean;
  disabled?: boolean;
  invalid?: boolean;
  id?: string;
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const matches = (needle: string, ...texts: (string | undefined)[]) =>
  texts.some((text) => text?.toLowerCase().includes(needle));

/**
 * A select whose options come in groups: a search over both, the groups on
 * the left and the picked group's options on the right. Built for the model
 * picker (configurations → models) and shared by every pick-one list too
 * long for a plain select, such as the trigger types.
 */
export function GroupedSelect({
  groups,
  value,
  onValueChange,
  placeholder,
  groupsTitle,
  itemsTitle,
  searchPlaceholder,
  noResults,
  emptyMessage,
  onAddGroup,
  showGroupInValue = true,
  disabled = false,
  invalid = false,
  id,
  className,
  open: controlledOpen,
  onOpenChange: setControlledOpen,
}: GroupedSelectProps) {
  const [popoverWidth, setPopoverWidth] = React.useState<string>("auto");
  const [popoverOpen, setPopoverOpen] = React.useState(false);
  const [activeGroupId, setActiveGroupId] = React.useState<string | null>(null);
  const [searchQuery, setSearchQuery] = React.useState("");
  const triggerRef = React.useRef<HTMLButtonElement>(null);

  const selectedGroup = groups.find((group) =>
    group.items.some((item) => item.id === value)
  );
  const selectedItem = selectedGroup?.items.find((item) => item.id === value);

  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : popoverOpen;

  const handleOpenChange = (open: boolean) => {
    if (isControlled) {
      setControlledOpen?.(open);
    } else {
      setPopoverOpen(open);
    }

    if (open && triggerRef.current) {
      setPopoverWidth(`${Math.max(triggerRef.current.offsetWidth, 400)}px`);
      // Open on the picked option's group, or on the first one.
      setActiveGroupId(selectedGroup?.id ?? groups[0]?.id ?? null);
    } else if (!open) {
      // The search goes; the group stays where it was left.
      setSearchQuery("");
    }
  };

  const handleSelect = (itemId: string) => {
    onValueChange(itemId);
    handleOpenChange(false);
  };

  const needle = searchQuery.trim().toLowerCase();
  // A group matching the search keeps all its options; otherwise only the
  // options that match it themselves.
  const groupMatches = (group: GroupedSelectGroup) =>
    !needle || matches(needle, group.label, group.description);
  const itemMatches = (item: GroupedSelectItem) =>
    matches(needle, item.label, item.description, item.searchText);
  const filteredGroups = needle
    ? groups.filter(
        (group) => groupMatches(group) || group.items.some(itemMatches)
      )
    : groups;
  // A search that hides the open group moves to the first one it leaves.
  const activeGroup =
    filteredGroups.find((group) => group.id === activeGroupId) ??
    filteredGroups[0];
  const filteredItems = activeGroup
    ? groupMatches(activeGroup)
      ? activeGroup.items
      : activeGroup.items.filter(itemMatches)
    : [];

  return (
    <Popover open={isOpen} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          ref={triggerRef}
          id={id}
          variant="outline"
          role="combobox"
          aria-expanded={isOpen}
          aria-invalid={invalid || undefined}
          // Bordered and filled like an Input beside it, not like an outline
          // button: the same line in both themes, no tint on hover.
          className={cn(
            "w-full justify-between rounded-md border-input bg-white px-3 text-foreground shadow-none hover:border-input hover:bg-white hover:text-foreground focus:border-primary focus-visible:border-primary focus-visible:ring-0 aria-[invalid=true]:border-destructive dark:border-zinc-700 dark:bg-zinc-900/60 dark:hover:border-zinc-700 dark:hover:bg-zinc-900/60 dark:focus:border-accent-foreground dark:focus-visible:border-accent-foreground",
            className
          )}
          disabled={disabled}
        >
          {selectedItem ? (
            <div className="flex min-w-0 items-center gap-2">
              <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
                {selectedItem.icon ?? selectedGroup?.icon}
              </div>
              {showGroupInValue ? (
                <div className="flex min-w-0 flex-col items-start">
                  <span className="max-w-full truncate text-xs">
                    {selectedItem.label}
                  </span>
                  <span className="max-w-full truncate text-[10px] font-normal leading-none text-muted-foreground">
                    {selectedGroup?.label}
                  </span>
                </div>
              ) : (
                // One line, set like any other field's value.
                <span className="truncate font-normal text-inputSize">
                  {selectedItem.label}
                </span>
              )}
            </div>
          ) : (
            <span className="font-normal text-inputSize text-muted-foreground">
              {placeholder}
            </span>
          )}
          <ChevronDown className="ml-2 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-0" style={{ width: popoverWidth }}>
        <div
          className={cn(
            "flex w-full flex-col",
            groups.length === 0 ? "h-[200px]" : "h-[270px]"
          )}
        >
          {groups.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-6">
              {emptyMessage}
            </div>
          ) : (
            <>
              <div className="border-b border-border">
                <div className="relative w-full">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 transform text-muted-foreground" />
                  <Input
                    placeholder={searchPlaceholder}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full border-none pl-9"
                  />
                </div>
              </div>

              <div className="flex h-full flex-1 overflow-hidden">
                <div className="flex w-[40%] flex-col border-r border-border bg-muted/20">
                  <div className="flex h-8 items-center justify-between border-b border-border px-2 py-1">
                    <h3 className="text-xs font-medium">{groupsTitle}</h3>
                    {onAddGroup && (
                      <Button
                        variant="secondary"
                        size="icon"
                        onClick={onAddGroup}
                        className="h-5 w-5"
                      >
                        <Plus />
                      </Button>
                    )}
                  </div>
                  <div className="flex-1 overflow-y-auto p-1">
                    {filteredGroups.map((group) => (
                      <button
                        key={group.id}
                        type="button"
                        onClick={() => setActiveGroupId(group.id)}
                        className={cn(
                          "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left transition-colors",
                          activeGroup?.id === group.id && "bg-accent/20"
                        )}
                      >
                        {group.icon && (
                          <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
                            {group.icon}
                          </div>
                        )}
                        <span className="min-w-0 truncate text-xs font-medium">
                          {group.label}
                          {group.description && (
                            <div className="truncate text-[10px] font-normal leading-none text-muted-foreground">
                              {group.description}
                            </div>
                          )}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex h-full w-[60%] flex-col overflow-hidden">
                  <div className="h-8 flex-shrink-0 border-b border-border px-2 py-2">
                    <h3 className="text-xs font-medium">{itemsTitle}</h3>
                  </div>
                  <div className="min-h-0 flex-1 overflow-hidden">
                    <Command className="flex h-full flex-col">
                      <CommandList className="flex-1 overflow-y-auto">
                        <CommandEmpty>{noResults}</CommandEmpty>
                        <CommandGroup>
                          {filteredItems.map((item) => (
                            <CommandItem
                              key={item.id}
                              value={`${item.id} ${item.label}`}
                              onSelect={() => handleSelect(item.id)}
                              className="relative overflow-hidden"
                            >
                              <div className="flex w-full items-center gap-3 overflow-hidden">
                                <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center">
                                  {item.icon ?? activeGroup?.icon}
                                </div>
                                <div className="flex min-w-0 flex-1 flex-col items-start overflow-hidden">
                                  <span className="w-full truncate text-xs font-medium">
                                    {item.label}
                                  </span>
                                  {item.description && (
                                    <span className="w-full truncate text-[10px] leading-snug text-muted-foreground">
                                      {item.description}
                                    </span>
                                  )}
                                </div>
                                {item.end}
                                <span className="w-4 shrink-0" />
                              </div>
                              <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
                                <Check
                                  className={cn(
                                    "h-4 w-4 text-accent dark:text-accent-foreground",
                                    value === item.id
                                      ? "opacity-100"
                                      : "opacity-0"
                                  )}
                                />
                              </span>
                            </CommandItem>
                          ))}
                        </CommandGroup>
                      </CommandList>
                    </Command>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

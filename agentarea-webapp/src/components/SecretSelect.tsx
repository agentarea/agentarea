"use client";

import { useState } from "react";
import { Check, ChevronDown, Plus } from "lucide-react";
import type { SecretResponse } from "@/api/client/types.gen";
import { CreateSecretDialog } from "@/app/w/[workspace]/(main)/secrets/components/CreateSecretDialog";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { cn } from "@/lib/utils";

export interface SelectableSecret {
  id: string;
  name: string;
}

/** Pick one workspace secret, or make one from the same dropdown.
 *
 * The last row opens the create dialog and selects what it made, so a form
 * asking for a secret never has to send the user to /secrets and back. It is a
 * combobox rather than a native select because the create row must not be a
 * selectable option — as one it lands in the value the form posts.
 */
export function SecretSelect({
  secrets,
  value,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyMessage,
  createLabel,
  id,
  name,
  ariaLabel,
  className,
  required,
  disabled,
  onCreated,
}: {
  secrets: SelectableSecret[];
  value: string;
  onChange: (secretId: string) => void;
  placeholder: string;
  searchPlaceholder: string;
  emptyMessage: string;
  /** Label of the row that opens the create dialog. */
  createLabel: string;
  id?: string;
  /** Set when the value has to reach a server action through the form post. */
  name?: string;
  ariaLabel?: string;
  className?: string;
  required?: boolean;
  disabled?: boolean;
  /** Lets the owner of the list refetch, so other pickers see the new secret. */
  onCreated?: (secret: SecretResponse) => void;
}) {
  // A refetch is not instant, and the list it returns may not have landed yet —
  // holding what was just created here keeps it selectable meanwhile, and keeps
  // it selectable at all when the list never loaded.
  const { canAdminister } = useViewerCapabilities();
  const [created, setCreated] = useState<SelectableSecret[]>([]);
  const [open, setOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const options = [
    ...secrets,
    ...created.filter((secret) => !secrets.some((s) => s.id === secret.id)),
  ];
  const selected = options.find((secret) => secret.id === value);

  return (
    <>
      <input type="hidden" name={name} value={value} />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            id={id}
            variant="outline"
            role="combobox"
            aria-expanded={open}
            aria-label={ariaLabel}
            aria-required={required}
            disabled={disabled && created.length === 0}
            className={cn(
              "h-10 w-full justify-between bg-white px-3 font-normal shadow-sm hover:bg-white dark:bg-zinc-900 dark:hover:bg-zinc-900",
              className
            )}
          >
            <span
              className={cn("truncate", !selected && "text-muted-foreground")}
            >
              {selected?.name ?? placeholder}
            </span>
            <ChevronDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-[var(--radix-popover-trigger-width)] p-0"
        >
          <Command>
            <CommandInput placeholder={searchPlaceholder} />
            <CommandList>
              <CommandEmpty>{emptyMessage}</CommandEmpty>
              <CommandGroup>
                {options.map((secret) => (
                  <CommandItem
                    key={secret.id}
                    value={secret.name}
                    onSelect={() => {
                      onChange(secret.id);
                      setOpen(false);
                    }}
                  >
                    <span className="truncate">{secret.name}</span>
                    <Check
                      className={cn(
                        "ml-auto h-4 w-4",
                        secret.id === value ? "opacity-100" : "opacity-0"
                      )}
                    />
                  </CommandItem>
                ))}
              </CommandGroup>
              <CommandSeparator />
              <CommandGroup>
                <CommandItem
                  value={createLabel}
                  className="text-muted-foreground"
                  disabled={!canAdminister}
                  onSelect={() => {
                    setOpen(false);
                    setDialogOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-3.5 w-3.5" />
                  {createLabel}
                </CommandItem>
                {!canAdminister && (
                  <AdminOnlyHint
                    action="createSecret"
                    className="px-2 pb-1.5"
                  />
                )}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <CreateSecretDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        showTrigger={false}
        onCreated={(secret) => {
          setCreated((previous) => [...previous, secret]);
          onChange(secret.id);
          onCreated?.(secret);
        }}
      />
    </>
  );
}

"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

export interface CheckboxListItem {
  value: string;
  label: string;
  /** A muted line under the label, e.g. the full name it shortens. */
  detail?: string;
}

/** A pick-several list of short monospace names, in the order given. */
export function CheckboxList({
  items,
  selected,
  onChange,
  disabled,
  className,
}: {
  items: CheckboxListItem[];
  selected: string[];
  onChange: (values: string[]) => void;
  disabled?: boolean;
  className?: string;
}) {
  const picked = new Set(selected);

  function toggle(value: string, on: boolean) {
    onChange(
      items
        .filter((i) => (i.value === value ? on : picked.has(i.value)))
        .map((i) => i.value)
    );
  }

  return (
    <ul className={cn("space-y-1.5", className)}>
      {items.map((item) => (
        <li key={item.value}>
          <label className="flex cursor-pointer items-start gap-2">
            <Checkbox
              className="mt-0.5"
              checked={picked.has(item.value)}
              disabled={disabled}
              onCheckedChange={(checked) =>
                toggle(item.value, checked === true)
              }
            />
            <span className="min-w-0">
              <span className="block font-mono text-xs">{item.label}</span>
              {item.detail && (
                <span
                  className="block truncate text-xs text-muted-foreground"
                  title={item.detail}
                >
                  {item.detail}
                </span>
              )}
            </span>
          </label>
        </li>
      ))}
    </ul>
  );
}

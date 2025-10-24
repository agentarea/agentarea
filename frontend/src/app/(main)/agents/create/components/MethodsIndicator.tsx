import React from "react";
import { Checkbox } from "@/components/ui/checkbox";

interface Method {
  name: string;
  display_name?: string;
  description?: string;
}

interface MethodsIndicatorProps {
  methods: Method[];
  selectedMethods: Record<string, boolean>;
  onSelectAll: (checked: boolean) => void;
  className?: string;
}

export const MethodsIndicator: React.FC<MethodsIndicatorProps> = ({
  methods,
  selectedMethods,
  onSelectAll,
  className = "",
}) => {
  if (!methods || methods.length === 0) {
    return null;
  }

  const selectedCount = methods.filter(
    (method) => selectedMethods[method.name] === true
  ).length;
  const totalCount = methods.length;
  const allSelected = selectedCount === totalCount;
  const someSelected = selectedCount > 0 && selectedCount < totalCount;

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Checkbox
        checked={allSelected}
        ref={(el) => {
          if (el) {
            const input = el.querySelector("input");
            if (input) {
              input.indeterminate = someSelected;
            }
          }
        }}
        onCheckedChange={onSelectAll}
        className="h-4 w-4 data-[state=checked]:border-primary data-[state=checked]:bg-primary"
        aria-label="Select all methods"
      />
      <span className="min-w-[50px] rounded-full bg-primary/15 px-2 py-0.5 text-center text-xs text-muted-foreground">
        {selectedCount}/{totalCount}
      </span>
    </div>
  );
};

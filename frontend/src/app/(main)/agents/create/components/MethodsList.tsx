import React from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import { MethodsIndicator } from "./MethodsIndicator";

export interface Method {
  name: string;
  display_name?: string;
  description?: string;
}

export interface MethodsListProps {
  methods: Method[];
  selectedMethods: Record<string, boolean>;
  onMethodToggle: (methodName: string, checked: boolean) => void;
  toolName: string;
  className?: string;
  onSelectAll?: (checked: boolean) => void;
  showSelectAll?: boolean;
}

export const MethodsList: React.FC<MethodsListProps> = ({
  methods,
  selectedMethods,
  onMethodToggle,
  toolName,
  className = "",
  onSelectAll,
  showSelectAll = false,
}) => {
  if (!methods || methods.length === 0) {
    return null;
  }

  return (
    <div className={cn(`space-y-1`, className)}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-foreground">
          Available Methods:
        </p>
        {showSelectAll && onSelectAll && (
          <MethodsIndicator
            methods={methods}
            selectedMethods={selectedMethods}
            onSelectAll={onSelectAll}
          />
        )}
      </div>
      <div className="max-h-60 space-y-1 overflow-y-auto pr-2">
        {methods.map((method) => {
          const methodId = `${toolName}-${method.name}`;
          const isChecked = selectedMethods[method.name] === true;

          return (
            <div
              key={method.name}
              className="flex items-center gap-2 rounded bg-muted/30 p-1"
            >
              <Checkbox
                id={methodId}
                checked={isChecked}
                onCheckedChange={(checked) =>
                  onMethodToggle(method.name, checked as boolean)
                }
                className="h-4 w-4 data-[state=checked]:border-primary data-[state=checked]:bg-primary"
              />
              <label
                htmlFor={methodId}
                className="flex flex-1 cursor-pointer items-center gap-2"
              >
                <span className="text-xs text-foreground">
                  {method.display_name || method.name}
                </span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {method.description}
                </span>
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
};

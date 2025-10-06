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
  showSelectAll = false
}) => {
  if (!methods || methods.length === 0) {
    return null;
  }


  return (
    <div className={cn(`space-y-1`, className)}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-foreground">Available Methods:</p>
        {showSelectAll && onSelectAll && (
          <MethodsIndicator
            methods={methods}
            selectedMethods={selectedMethods}
            onSelectAll={onSelectAll}
          />
        )}
      </div>
      <div className="space-y-1">
        {methods.map((method) => {
          const methodId = `${toolName}-${method.name}`;
          const isChecked = selectedMethods[method.name] === true;
          
          return (
            <div key={method.name} className="flex items-center gap-2 p-1 rounded bg-muted/30">
              <Checkbox
                id={methodId}
                checked={isChecked}
                onCheckedChange={(checked) => 
                  onMethodToggle(method.name, checked as boolean)
                }
                className="h-4 w-4 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
              />
              <label 
                htmlFor={methodId}
                className="flex-1 flex items-center gap-2 cursor-pointer"
              >
                <span className="text-xs text-foreground">
                  {method.display_name || method.name}
                </span>
                <span className="text-xs text-muted-foreground ml-auto">
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

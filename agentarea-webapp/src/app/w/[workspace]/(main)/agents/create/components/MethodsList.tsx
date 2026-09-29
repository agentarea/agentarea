import React from "react";
import { ShieldCheck } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";
import Divider from "@/components/ui/divider";

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
  /** Optional per-item approval state. When provided, shows approval toggle. */
  approvalStates?: Record<string, boolean>;
  onApprovalToggle?: (methodName: string, requiresApproval: boolean) => void;
  /** Label override (default: "Available Methods:") */
  label?: string;
}

export const MethodsList: React.FC<MethodsListProps> = ({
  methods,
  selectedMethods,
  onMethodToggle,
  toolName,
  className = "",
  onSelectAll,
  showSelectAll = false,
  approvalStates,
  onApprovalToggle,
  label = "Available Methods:",
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
    <div className={cn(`space-y-1`, className)}>
        <p className="text-xs font-medium text-foreground">
          {label}
        </p>
        {showSelectAll && onSelectAll && (
        <div className="flex items-center gap-2 pl-1">
          <Checkbox
            id={`${toolName}-select-all`}
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
            aria-label="Select all"
          />
          <label
            htmlFor={`${toolName}-select-all`}
            className="cursor-pointer text-xs text-foreground"
          >
            Select all
          </label>
        </div>
        )}
      <Divider />
      <div className="max-h-60 space-y-1 overflow-y-auto pr-2">
        {methods.map((method) => {
          const methodId = `${toolName}-${method.name}`;
          const isChecked = selectedMethods[method.name] === true;
          const needsApproval = approvalStates?.[method.name] === true;

          return (
            <div
              key={method.name}
              className={cn(
                "flex items-center gap-2 rounded p-1",
                isChecked ? "bg-muted/30" : "bg-muted/10 opacity-60"
              )}
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
                <span className={cn(
                  "text-xs",
                  isChecked ? "text-foreground" : "text-muted-foreground line-through"
                )}>
                  {method.display_name || method.name}
                </span>
                {!onApprovalToggle && (
                  <span className="ml-auto text-xs text-muted-foreground line-clamp-1">
                    {method.description}
                  </span>
                )}
              </label>
              {onApprovalToggle && isChecked && (
                <button
                  type="button"
                  className={cn(
                    "ml-auto flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-colors",
                    needsApproval
                      ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                      : "bg-muted/40 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                  )}
                  onClick={() => onApprovalToggle(method.name, !needsApproval)}
                  title={
                    needsApproval
                      ? "Requires human approval — click to auto-approve"
                      : "Auto-approved — click to require approval"
                  }
                >
                  <ShieldCheck className="h-3 w-3" />
                  {needsApproval ? "Approval required" : "Auto"}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

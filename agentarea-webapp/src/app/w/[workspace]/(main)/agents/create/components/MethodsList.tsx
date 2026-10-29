import React from "react";
import { useTranslations } from "next-intl";
import { ShieldCheck } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import Divider from "@/components/ui/divider";
import { cn } from "@/lib/utils";

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
  /** Label override (default: "Available methods") */
  label?: string;
  /** Two columns on a wide screen, where the list has the room. */
  wide?: boolean;
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
  label,
  wide = false,
}) => {
  const t = useTranslations("MethodsList");

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
    <div className={className}>
      <p className="text-xs font-medium text-foreground">
        {label ?? t("availableMethods")}
      </p>
      {showSelectAll && onSelectAll && (
        <div className="mt-1.5 flex items-center gap-2 px-1.5">
          <Checkbox
            id={`${toolName}-select-all`}
            checked={allSelected}
            indeterminate={someSelected}
            onCheckedChange={(checked) => onSelectAll(checked === true)}
          />
          <label
            htmlFor={`${toolName}-select-all`}
            className="cursor-pointer text-xs text-foreground"
          >
            {t("selectAll")}
          </label>
        </div>
      )}
      <Divider className="my-2" />
      <div
        className={cn(
          "max-h-60 space-y-0.5 overflow-y-auto",
          wide && "lg:grid lg:grid-cols-2 lg:gap-x-4 lg:gap-y-0.5 lg:space-y-0"
        )}
      >
        {methods.map((method) => {
          const methodId = `${toolName}-${method.name}`;
          const isChecked = selectedMethods[method.name] === true;
          const needsApproval = approvalStates?.[method.name] === true;

          return (
            <div
              key={method.name}
              className="flex items-start gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-muted/50"
            >
              <Checkbox
                id={methodId}
                checked={isChecked}
                onCheckedChange={(checked) =>
                  onMethodToggle(method.name, checked === true)
                }
                className="mt-px"
              />
              {/* Name over its description, so a long name never runs into it. */}
              <label
                htmlFor={methodId}
                className="min-w-0 flex-1 cursor-pointer"
              >
                <span
                  className={cn(
                    "block text-xs font-medium leading-4",
                    isChecked
                      ? "text-foreground"
                      : "text-muted-foreground line-through"
                  )}
                >
                  {method.display_name || method.name}
                </span>
                {method.description && (
                  <span className="mt-0.5 block truncate text-[11px] leading-4 text-muted-foreground">
                    {method.description}
                  </span>
                )}
              </label>
              {onApprovalToggle && isChecked && (
                <button
                  type="button"
                  className={cn(
                    "flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] transition-colors",
                    needsApproval
                      ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                      : "bg-muted/40 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                  )}
                  onClick={() => onApprovalToggle(method.name, !needsApproval)}
                  title={
                    needsApproval
                      ? t("approvalRequiredHint")
                      : t("autoApprovedHint")
                  }
                >
                  <ShieldCheck className="h-3 w-3" />
                  {needsApproval ? t("approvalRequired") : t("autoApproved")}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

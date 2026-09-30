"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Play } from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useCurrency } from "@/hooks/useCurrency";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import {
  continuationFields,
  defaultContinuationForm,
  limitField,
  parseContinuationGrant,
  type ContinuationField,
  type ContinuationForm,
} from "@/lib/continuation";
import { cn } from "@/lib/utils";

const INPUT_PROPS: Record<
  ContinuationField,
  { min: string; max?: string; step: string; width: string }
> = {
  iterations: { min: "0", max: "1000", step: "1", width: "w-32" },
  budget: { min: "0.01", step: "0.01", width: "w-44" },
  tokens: { min: "0", max: "10000000", step: "1000", width: "w-40" },
  toolCalls: { min: "0", max: "10000", step: "1", width: "w-36" },
};

interface ContinuationGrantFormProps {
  taskId: string;
  failureReason: string | null;
  onContinued?: () => Promise<void> | void;
  className?: string;
}

export function ContinuationGrantForm({
  taskId,
  failureReason,
  onContinued,
  className,
}: ContinuationGrantFormProps) {
  const t = useTranslations("Chat.continuation");
  const { currency } = useCurrency();
  const [edits, setEdits] = useState<Partial<ContinuationForm>>({});
  const [continuing, setContinuing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const limit = limitField(failureReason);
  const form: ContinuationForm = {
    ...defaultContinuationForm(failureReason),
    ...edits,
  };

  const label = (field: ContinuationField) => {
    const base = t(`fields.${field}`, { currency: currency ?? "¤" });
    return limit === null || field === limit
      ? base
      : t("optionalField", { label: base });
  };

  const handleContinue = async () => {
    setError(null);
    const grant = parseContinuationGrant(form, failureReason);
    if (!grant.ok) {
      setError(t(`errors.${grant.error}`));
      return;
    }

    setContinuing(true);
    try {
      const { continueAgentTaskAction } = await import("@/lib/server-actions");
      const result = await continueAgentTaskAction(taskId, grant.payload);
      if (result.error) {
        setError(apiErrorMessage(result, t("failed")));
        return;
      }
      setEdits({});
      await onContinued?.();
    } catch (caught) {
      console.error("Failed to continue task", caught);
      setError(`${t("failed")}: ${formatApiError(caught)}`);
    } finally {
      setContinuing(false);
    }
  };

  return (
    <div
      className={cn(
        "space-y-3 rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30",
        className
      )}
    >
      <div>
        <StatusIndicator kind="attention" size="sm">
          {t(`title.${limit === null ? "unknown" : failureReason}`)}
        </StatusIndicator>
        <p className="text-xs text-amber-800 dark:text-amber-300">
          {t("hint")}
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {continuationFields(failureReason).map((field) => {
          const input = INPUT_PROPS[field];
          return (
            <label key={field} className="space-y-1 text-xs font-medium">
              {label(field)}
              <input
                className={cn(
                  "block h-9 rounded-md border bg-background px-3 text-sm",
                  input.width
                )}
                min={input.min}
                max={input.max}
                step={input.step}
                type="number"
                value={form[field]}
                onChange={(event) => {
                  const value = event.target.value;
                  setEdits((current) => ({ ...current, [field]: value }));
                  setError(null);
                }}
              />
            </label>
          );
        })}
        <Button onClick={handleContinue} disabled={continuing}>
          {continuing ? (
            <Loader2 className="mr-2 animate-spin" />
          ) : (
            <Play className="mr-2" />
          )}
          {t("submit")}
        </Button>
      </div>
      {error && <FormError>{error}</FormError>}
    </div>
  );
}

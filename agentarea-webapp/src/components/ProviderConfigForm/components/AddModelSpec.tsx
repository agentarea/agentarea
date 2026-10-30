import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import type { AgentareaApiApiV1ModelSpecsModelSpecResponse as ModelSpecResponse } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-errors";
import { upsertModelSpecAction } from "@/lib/server-actions";
import {
  ManualModelSpec,
  manualModelSpecSchema,
  toModelSpecCreate,
} from "./manualModelSpec";

const EMPTY: ManualModelSpec = {
  model_name: "",
  context_window: "",
  input_per_million: "",
  output_per_million: "",
};

const FIELDS = [
  { name: "model_name", label: "manualModelName", placeholder: "llama3.1:8b" },
  { name: "context_window", label: "manualContextWindow", placeholder: "131072" },
  { name: "input_per_million", label: "manualInputPrice", placeholder: "0.15", optional: true },
  { name: "output_per_million", label: "manualOutputPrice", placeholder: "0.60", optional: true },
] as const;

type AddModelSpecProps = {
  providerSpecId: string;
  onAdded: (spec: ModelSpecResponse) => Promise<void> | void;
};

export default function AddModelSpec({ providerSpecId, onAdded }: AddModelSpecProps) {
  const t = useTranslations("ProviderConfigForm");
  const tCommon = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const {
    control,
    handleSubmit,
    reset,
    formState: { errors, isValid },
  } = useForm<ManualModelSpec>({
    resolver: zodResolver(manualModelSpecSchema),
    defaultValues: EMPTY,
    mode: "onChange",
  });

  if (!open) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="h-7 gap-1.5 text-xs"
      >
        <Plus />
        {t("addModelManually")}
      </Button>
    );
  }

  const add = (values: ManualModelSpec) => {
    setError(null);
    startTransition(async () => {
      const result = await upsertModelSpecAction(toModelSpecCreate(providerSpecId, values));
      if (result.error || !result.data) {
        setError(apiErrorMessage(result, t("failedToAddModel")));
        return;
      }
      await onAdded(result.data);
      reset(EMPTY);
      setOpen(false);
    });
  };

  return (
    <div
      className="space-y-3 rounded-md border p-3"
      onKeyDown={(event) => {
        // Enter here adds the model; it must not submit the provider form around it.
        if (event.key !== "Enter") return;
        event.preventDefault();
        if (isValid && !pending) void handleSubmit(add)();
      }}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {FIELDS.map((field) => (
          <div key={field.name} className="space-y-1">
            <FormLabel
              htmlFor={`manual-${field.name}`}
              optional={"optional" in field}
              required={!("optional" in field)}
            >
              {t(field.label)}
            </FormLabel>
            <Controller
              name={field.name}
              control={control}
              render={({ field: input }) => (
                <Input
                  id={`manual-${field.name}`}
                  inputMode={field.name === "model_name" ? undefined : "decimal"}
                  value={input.value}
                  onChange={input.onChange}
                  onBlur={input.onBlur}
                  placeholder={field.placeholder}
                />
              )}
            />
            {errors[field.name] && (
              <p className="form-error">{t(`${field.label}Invalid`)}</p>
            )}
          </div>
        ))}
      </div>
      <p className="note">{t("manualPriceHint")}</p>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="xs"
          onClick={() => {
            reset(EMPTY);
            setError(null);
            setOpen(false);
          }}
        >
          {tCommon("cancel")}
        </Button>
        <Button
          type="button"
          size="xs"
          disabled={!isValid || pending}
          onClick={handleSubmit(add)}
        >
          {pending ? t("addingModel") : t("addModel")}
        </Button>
      </div>
    </div>
  );
}

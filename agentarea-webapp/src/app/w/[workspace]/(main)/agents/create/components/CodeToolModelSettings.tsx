import type {
  ModelInstanceResponse,
  ModelKind,
} from "@/api/client/types.gen";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import { Control, UseFormSetValue, useWatch } from "react-hook-form";
import FormError from "@/components/FormError";
import Link from "@/components/WorkspaceLink";
import { Button } from "@/components/ui/button";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { listModelInstancesAction } from "@/lib/server-actions";
import type { AgentFormValues, CodeToolModelIds } from "../types";

type ModelField = keyof CodeToolModelIds;
type SettingsKind = Extract<ModelKind, "image" | "video" | "decision">;

const MODEL_FIELDS: Record<
  string,
  { field: ModelField; kind: SettingsKind }[]
> = {
  "agentarea/media": [
    { field: "image_model_id", kind: "image" },
    { field: "video_model_id", kind: "video" },
  ],
  "agentarea/decide": [{ field: "model_id", kind: "decision" }],
};

function KindModelSelect({
  kind,
  value,
  onChange,
}: {
  kind: SettingsKind;
  value: string | null | undefined;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations("AgentsPage.create.codeToolModels");
  const tCommon = useTranslations("Common");
  const [instances, setInstances] = useState<ModelInstanceResponse[] | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    listModelInstancesAction({ kind, is_active: true })
      .then((result) => {
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("loadFailed")));
          return;
        }
        setInstances(result.data);
      })
      .catch((err: unknown) => {
        console.error(`Failed to load ${kind} models`, err);
        setError(`${t("loadFailed")}: ${formatApiError(err)}`);
      });
  }, [kind, t]);

  useEffect(() => {
    load();
  }, [load]);

  const label = t(`${kind}.label`);

  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-foreground">
        {label}
      </div>
      {error ? (
        <div className="flex flex-col items-start gap-2">
          <FormError className="w-full">{error}</FormError>
          <Button type="button" variant="outline" size="sm" onClick={load}>
            {tCommon("retry")}
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <ProviderModelSelector
            modelInstances={instances ?? []}
            value={value ?? undefined}
            onValueChange={onChange}
            disabled={instances === null}
            placeholder={t("placeholder")}
            emptyMessage={
              <div className="text-center text-sm text-muted-foreground">
                <p>{t(`${kind}.empty`)}</p>
                <Link href="/models" className="text-primary underline">
                  {t("addModel")}
                </Link>
              </div>
            }
          />
          {value && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => onChange(null)}
              className="h-8 w-8 shrink-0 text-muted-foreground"
              aria-label={t("clear", { label })}
            >
              <X />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export function CodeToolModelSettings({
  toolName,
  index,
  control,
  setValue,
}: {
  toolName: string;
  index: number;
  control: Control<AgentFormValues>;
  setValue: UseFormSetValue<AgentFormValues>;
}) {
  const t = useTranslations("AgentsPage.create.codeToolModels");
  const tool = useWatch({
    control,
    name: `tools_config.builtin_tools.${index}`,
  });
  const fields = MODEL_FIELDS[toolName] ?? [];
  if (fields.length === 0) return null;

  const missing = fields.every(({ field }) => !tool?.[field]);

  return (
    <div className="space-y-3 rounded-md border bg-muted/20 p-3">
      {fields.map(({ field, kind }) => (
        <KindModelSelect
          key={field}
          kind={kind}
          value={tool?.[field]}
          onChange={(value) =>
            setValue(`tools_config.builtin_tools.${index}.${field}`, value, {
              shouldDirty: true,
            })
          }
        />
      ))}
      {missing && (
        <p className="text-xs text-muted-foreground">
          {fields.length > 1 ? t("pickAtLeastOne") : t("pickOne")}
        </p>
      )}
    </div>
  );
}

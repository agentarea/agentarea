import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ImageIcon, Video, X, type LucideIcon } from "lucide-react";
import { Control, UseFormSetValue, useWatch } from "react-hook-form";
import type { ModelInstanceResponse, ModelKind } from "@/api/client/types.gen";
import ConfigSheet from "@/components/ConfigSheet";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import ProviderConfigForm from "@/components/ProviderConfigForm/ProviderConfigForm";
import { Button } from "@/components/ui/button";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { listModelInstancesAction } from "@/lib/server-actions";
import type { AgentFormValues, CodeToolModelIds } from "../types";

type ModelField = keyof CodeToolModelIds;
type SettingsKind = Extract<ModelKind, "image" | "video">;

const MODEL_FIELDS: Record<
  string,
  { field: ModelField; kind: SettingsKind }[]
> = {
  "agentarea/media": [
    { field: "image_model_id", kind: "image" },
    { field: "video_model_id", kind: "video" },
  ],
};

/** Whether a toolset asks for models of its own. */
export const hasCodeToolModelSettings = (toolName: string) =>
  toolName in MODEL_FIELDS;

const KIND_ICONS: Record<SettingsKind, LucideIcon> = {
  image: ImageIcon,
  video: Video,
};

/** A model of one kind, picked the way the form picks the agent's LLM model. */
function KindModelSelect({
  id,
  kind,
  value,
  onChange,
}: {
  id: string;
  kind: SettingsKind;
  value: string | null | undefined;
  onChange: (value: string | null) => void;
}) {
  const t = useTranslations("AgentsPage.create.codeToolModels");
  const tCreate = useTranslations("AgentsPage.create");
  const tCommon = useTranslations("Common");
  const [instances, setInstances] = useState<ModelInstanceResponse[] | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [selectOpen, setSelectOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);

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

  const addModel = () => {
    setSelectOpen(false);
    setSheetOpen(true);
  };

  const label = t(`${kind}.label`);

  return (
    <div className="space-y-2">
      <FormLabel htmlFor={id} icon={KIND_ICONS[kind]}>
        {label}
      </FormLabel>
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
            open={selectOpen}
            onOpenChange={setSelectOpen}
            onAddProvider={addModel}
            emptyMessage={
              <div className="flex flex-col items-center gap-2 px-6">
                <div>{t(`${kind}.empty`)}</div>
                <div className="note">
                  {tCreate("createAndUseProviderConfiguration")}
                </div>
                <Button
                  type="button"
                  size="sm"
                  onClick={addModel}
                  className="mt-2"
                >
                  {t("addModel")}
                </Button>
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
      <ConfigSheet
        title={tCreate("createConfiguration")}
        className="md:min-w-[500px]"
        description=""
        triggerClassName="hidden"
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      >
        <ProviderConfigForm
          className="overflow-y-auto pb-6"
          onAfterSubmit={() => {
            load();
            setSheetOpen(false);
          }}
          onCancel={() => setSheetOpen(false)}
          isClear={true}
          autoRedirect={false}
        />
      </ConfigSheet>
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
    <div className="space-y-4">
      {fields.map(({ field, kind }) => (
        <KindModelSelect
          key={field}
          id={`builtin-tool-${index}-${field}`}
          kind={kind}
          value={tool?.[field]}
          onChange={(value) =>
            setValue(`tools_config.builtin_tools.${index}.${field}`, value, {
              shouldDirty: true,
            })
          }
        />
      ))}
      {missing && <p className="note">{t("pickAtLeastOne")}</p>}
    </div>
  );
}

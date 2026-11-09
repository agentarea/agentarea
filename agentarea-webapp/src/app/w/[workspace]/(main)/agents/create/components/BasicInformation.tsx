import React, { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Bot, Brain, Cpu, FileText, MessageSquare } from "lucide-react";
import {
  Control,
  Controller,
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
  useWatch,
} from "react-hook-form";
import type {
  ClientResponse,
  ModelInstanceResponse,
} from "@/api/client/types.gen";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { HarnessIcon } from "@/components/harnesses";
import ProviderConfigForm from "@/components/ProviderConfigForm/ProviderConfigForm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MarkdownTextarea } from "@/components/ui/markdown-textarea";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { offeredLevel, runnerModel, runnerModels } from "@/lib/runner-models";
import type { AgentFormValues } from "../../create/types";
import {
  listRunnerClientsAction,
  setRunnerModelAction,
} from "../../shared/runnerClientActions";
import { getNestedErrorMessage } from "../utils/formUtils";

// The Selects' values for "no client" and "the model's level": Radix refuses an empty item value.
const PLATFORM = "platform";
const MODEL_DEFAULT = "default";
const ClientIcon = ENTITY_ICONS.client;

type LLMModelInstance = ModelInstanceResponse;

type BasicInformationProps = {
  register: UseFormRegister<AgentFormValues>;
  control: Control<AgentFormValues>;
  errors: FieldErrors<AgentFormValues>;
  setValue: UseFormSetValue<AgentFormValues>;
  llmModelInstances: LLMModelInstance[];
  suggestedName?: string;
  onOpenConfigSheet?: () => void;
  onRefreshModels?: () => void;
};

const BasicInformation = ({
  register,
  control,
  errors,
  setValue,
  llmModelInstances,
  onRefreshModels,
  suggestedName,
}: BasicInformationProps) => {
  const [searchableSelectOpen, setSearchableSelectOpen] = useState(false);
  const [configSheetOpen, setConfigSheetOpen] = useState(false);
  const configSheetTriggerRef = useRef<HTMLButtonElement>(null);
  const t = useTranslations("AgentsPage.create");
  const [nameReady, setNameReady] = useState(!suggestedName);
  useEffect(() => {
    if (suggestedName) setNameReady(true);
  }, [suggestedName]);

  const [runnerClients, setRunnerClients] = useState<ClientResponse[]>([]);
  const [runnerError, setRunnerError] = useState<string | null>(null);
  useEffect(() => {
    void listRunnerClientsAction().then((result) => {
      if (result.ok) setRunnerClients(result.clients);
      else setRunnerError(result.error);
    });
  }, []);
  const clientId = useWatch({ control, name: "client_id" });
  const runnerClient = runnerClients.find((c) => c.id === clientId) ?? null;
  const reasoningEffort = useWatch({ control, name: "reasoning_effort" });
  const currentRunnerModel = runnerClient
    ? runnerModel(runnerClient, runnerClient.default_model)
    : null;

  const keepOfferedLevel = (client: ClientResponse | undefined) => {
    const model = client ? runnerModel(client, client.default_model) : null;
    const level = offeredLevel(model, reasoningEffort);
    if (level !== (reasoningEffort ?? "")) {
      setValue("reasoning_effort", level, { shouldDirty: true });
    }
  };

  const saveRunnerModel = (model: string) => {
    if (!runnerClient) return;
    void setRunnerModelAction(runnerClient.id, model).then((result) => {
      if (result.ok) {
        setRunnerClients((all) =>
          all.map((c) => (c.id === result.client.id ? result.client : c))
        );
        keepOfferedLevel(result.client);
        setRunnerError(null);
      } else {
        setRunnerError(result.error);
      }
    });
  };

  const handleConfigSheetOpenChange = (open: boolean) => {
    setConfigSheetOpen(open);
    if (open) {
      // Close SearchableSelect when ConfigSheet opens
      setSearchableSelectOpen(false);
    }
  };

  const handleCreateConfigClick = () => {
    // Programmatically click the ConfigSheet trigger button
    configSheetTriggerRef.current?.click();
    setSearchableSelectOpen(false);
  };

  const handleAfterSubmit = () => {
    // Обновить список моделей после создания конфигурации
    onRefreshModels?.();
    // Закрыть sheet после успешного создания
    setConfigSheetOpen(false);
  };

  const handleCancel = () => {
    // Закрыть sheet при отмене
    setConfigSheetOpen(false);
  };

  return (
    <div>
      {/* <h2 className="mb-6 label">
        <Sparkles className="h-5 w-5 text-accent" /> Basic Information
      </h2> */}
      <div className="form-content">
        {/* Name and model side by side where the form is wide enough. */}
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-2">
            <FormLabel htmlFor="name" icon={Bot} required>
              {t("agentName")}
            </FormLabel>
            <Input
              id="name"
              {...register("name", { required: t("nameRequired") })}
              readOnly={Boolean(suggestedName) && !nameReady}
              defaultValue={suggestedName}
              onFocus={
                suggestedName
                  ? (event) => {
                      if (event.currentTarget.value === suggestedName) {
                        event.currentTarget.select();
                      }
                    }
                  : undefined
              }
              placeholder={t("agentNamePlaceholder")}
              // className="mt-2 text-lg px-4 py-3 border-2 border-slate-200 focus:border-blue-400 transition-colors"
              aria-invalid={!!getNestedErrorMessage(errors, "name")}
            />
            {getNestedErrorMessage(errors, "name") && (
              <p className="form-error">
                {getNestedErrorMessage(errors, "name")}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="client_id" icon={ClientIcon}>
              {t("runsOn")}
            </FormLabel>
            <Controller
              name="client_id"
              control={control}
              render={({ field }) => (
                <Select
                  value={field.value || PLATFORM}
                  onValueChange={(value) => {
                    field.onChange(value === PLATFORM ? "" : value);
                    if (value !== PLATFORM) {
                      keepOfferedLevel(
                        runnerClients.find((c) => c.id === value)
                      );
                    }
                  }}
                >
                  <SelectTrigger id="client_id">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={PLATFORM}>
                      {t("runsOnPlatform")}
                    </SelectItem>
                    {runnerClients.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        <span className="inline-flex items-center gap-2">
                          <HarnessIcon kind={c.kind} className="h-4 w-4" />
                          {c.name}
                          {c.online ? "" : ` · ${t("runsOnOffline")}`}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <p className="note">{t("runsOnHint")}</p>
            {runnerError && <p className="form-error">{runnerError}</p>}
          </div>
          {runnerClient ? (
            <div className="space-y-2">
              <FormLabel htmlFor="runner_model" icon={Cpu}>
                {t("runnerModel")}
              </FormLabel>
              {runnerModels(runnerClient).length > 0 ? (
                <Select
                  value={runnerClient.default_model ?? undefined}
                  onValueChange={saveRunnerModel}
                >
                  <SelectTrigger id="runner_model">
                    <SelectValue placeholder={t("selectModel")} />
                  </SelectTrigger>
                  <SelectContent>
                    {runnerModels(runnerClient).map((model) => (
                      <SelectItem key={model.name} value={model.name}>
                        {model.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="note">{t("runnerModelsPending")}</p>
              )}
              <p className="note">{t("runnerModelHint")}</p>
            </div>
          ) : (
            <div className="space-y-2">
              <FormLabel htmlFor="model_id" icon={Cpu} required>
                {t("llmModel")}
              </FormLabel>
              <Controller
                name="model_id"
                control={control}
                rules={{ required: t("modelRequired") }}
                render={({ field }) => (
                  <ProviderModelSelector
                    modelInstances={llmModelInstances}
                    value={field.value}
                    onValueChange={field.onChange}
                    placeholder={t("selectModel")}
                    open={searchableSelectOpen}
                    onOpenChange={setSearchableSelectOpen}
                    onAddProvider={handleCreateConfigClick}
                    emptyMessage={
                      <div className="flex flex-col items-center gap-2 px-6">
                        <div>{t("noConfigurationsYet")}</div>
                        <div className="note">
                          {t("createAndUseProviderConfiguration")}
                        </div>
                        <Button
                          size="sm"
                          onClick={handleCreateConfigClick}
                          className="mt-2"
                        >
                          {t("createConfiguration")}
                        </Button>
                      </div>
                    }
                  />
                )}
              />
              {getNestedErrorMessage(errors, "model_id") && (
                <p className="form-error">
                  {getNestedErrorMessage(errors, "model_id")}
                </p>
              )}
            </div>
          )}
          {currentRunnerModel &&
            currentRunnerModel.reasoningLevels.length > 0 && (
              <div className="space-y-2">
                <FormLabel htmlFor="reasoning_effort" icon={Brain}>
                  {t("reasoningLevel")}
                </FormLabel>
                <Controller
                  name="reasoning_effort"
                  control={control}
                  render={({ field }) => (
                    <Select
                      value={field.value || MODEL_DEFAULT}
                      onValueChange={(value) =>
                        field.onChange(value === MODEL_DEFAULT ? "" : value)
                      }
                    >
                      <SelectTrigger id="reasoning_effort">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={MODEL_DEFAULT}>
                          {currentRunnerModel.defaultReasoning
                            ? t("reasoningModelDefaultLevel", {
                                level: currentRunnerModel.defaultReasoning,
                              })
                            : t("reasoningModelDefault")}
                        </SelectItem>
                        {currentRunnerModel.reasoningLevels.map((level) => (
                          <SelectItem key={level} value={level}>
                            {level}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
                <p className="note">{t("reasoningLevelHint")}</p>
              </div>
            )}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="description" icon={FileText} optional>
            {t("description")}
          </FormLabel>
          <Textarea
            id="description"
            {...register("description")}
            placeholder={t("descriptionPlaceholder")}
            // Two lines to start, growing with the text up to 15rem.
            className="min-h-[60px] max-h-60 resize-none [field-sizing:content]"
            aria-invalid={!!getNestedErrorMessage(errors, "description")}
          />
          {getNestedErrorMessage(errors, "description") && (
            <p className="form-error">
              {getNestedErrorMessage(errors, "description")}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="instruction" icon={MessageSquare}>
            {t("instruction")}
          </FormLabel>
          <Controller
            name="instruction"
            control={control}
            render={({ field }) => (
              <MarkdownTextarea
                id="instruction"
                value={field.value || ""}
                onChange={field.onChange}
                placeholder={t("instructionPlaceholder")}
                // Grows with the instruction, scrolling only past half the screen.
                className="min-h-[200px] max-h-[50vh] resize-none"
                aria-invalid={!!getNestedErrorMessage(errors, "instruction")}
              />
            )}
          />
          {getNestedErrorMessage(errors, "instruction") && (
            <p className="form-error">
              {getNestedErrorMessage(errors, "instruction")}
            </p>
          )}
        </div>
      </div>

      {/* ConfigSheet rendered outside of SearchableSelect */}
      <ConfigSheet
        title={t("createConfiguration")}
        className="md:min-w-[500px]"
        description=""
        triggerClassName="hidden"
        open={configSheetOpen}
        onOpenChange={handleConfigSheetOpenChange}
        triggerRef={configSheetTriggerRef}
      >
        <ProviderConfigForm
          className="overflow-y-auto pb-6"
          onAfterSubmit={handleAfterSubmit}
          onCancel={handleCancel}
          isClear={true}
          autoRedirect={false}
        />
      </ConfigSheet>
    </div>
  );
};

export default BasicInformation;

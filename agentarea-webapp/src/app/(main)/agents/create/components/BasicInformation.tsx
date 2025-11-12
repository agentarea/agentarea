import React, { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Bot, Cpu, FileText, MessageSquare } from "lucide-react";
import {
  Controller,
  FieldErrors,
  UseFormRegister,
  UseFormSetValue,
} from "react-hook-form";
import type { components } from "@/api/schema";
import FormLabel from "@/components/FormLabel/FormLabel";
import ProviderConfigForm from "@/components/ProviderConfigForm/ProviderConfigForm";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownTextarea } from "@/components/ui/markdown-textarea";
import type { AgentFormValues } from "../../create/types";
import { getNestedErrorMessage } from "../utils/formUtils";
import ConfigSheet from "./ConfigSheet";

type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

type BasicInformationProps = {
  register: UseFormRegister<AgentFormValues>;
  control: any;
  errors: FieldErrors<AgentFormValues>;
  setValue: UseFormSetValue<AgentFormValues>;
  llmModelInstances: LLMModelInstance[];
  onOpenConfigSheet?: () => void;
  onRefreshModels?: () => void;
};

const BasicInformation = ({
  register,
  control,
  errors,
  setValue,
  llmModelInstances,
  onOpenConfigSheet,
  onRefreshModels,
}: BasicInformationProps) => {
  const [searchableSelectOpen, setSearchableSelectOpen] = useState(false);
  const [configSheetOpen, setConfigSheetOpen] = useState(false);
  const configSheetTriggerRef = useRef<HTMLButtonElement>(null);
  const t = useTranslations("AgentsPage.create");

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

  const handleAfterSubmit = (config: any) => {
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
    <Card className="">
      {/* <h2 className="mb-6 label">
        <Sparkles className="h-5 w-5 text-accent" /> Basic Information
      </h2> */}
      <div className="form-content">
        <div className="space-y-2">
          <FormLabel htmlFor="name" icon={Bot}>
            {t("agentName")}
          </FormLabel>
          <Input
            id="name"
            {...register("name", { required: "Agent name is required" })}
            placeholder={t("agentNamePlaceholder")}
            // className="mt-2 text-lg px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors"
            aria-invalid={!!getNestedErrorMessage(errors, "name")}
          />
          {getNestedErrorMessage(errors, "name") && (
            <p className="form-error">
              {getNestedErrorMessage(errors, "name")}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="model_id" icon={Cpu}>
            {t("llmModel")}
          </FormLabel>
          <Controller
            name="model_id"
            control={control}
            rules={{ required: "Model is required" }}
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
        <div className="space-y-2">
          <FormLabel htmlFor="description" icon={FileText} optional>
            {t("description")}
          </FormLabel>
          <Textarea
            id="description"
            {...register("description")}
            placeholder={t("descriptionPlaceholder")}
            className="h-[100px] resize-none"
            // className="mt-2 text-base px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors h-32"
            aria-invalid={!!getNestedErrorMessage(errors, "description")}
          />
          {getNestedErrorMessage(errors, "description") && (
            <p className="form-error">
              {getNestedErrorMessage(errors, "description")}
            </p>
          )}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="instruction" icon={MessageSquare} required>
            {t("instruction")}
          </FormLabel>
          <Controller
            name="instruction"
            control={control}
            rules={{ required: "Instruction is required" }}
            render={({ field }) => (
              <MarkdownTextarea
                id="instruction"
                value={field.value || ""}
                onChange={field.onChange}
                placeholder={t("instructionPlaceholder")}
                className="h-[200px] resize-none"
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
    </Card>
  );
};

export default BasicInformation;

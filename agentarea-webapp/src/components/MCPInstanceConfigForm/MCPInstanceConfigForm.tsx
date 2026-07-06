"use client";

import type { McpServerResponse } from "@/api/client/types.gen";
import React from "react";
import { Info, Server, FileText, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type MCPServer = McpServerResponse;

export interface MCPInstanceConfigFormProps {
  server: MCPServer;
  instanceName: string;
  instanceDescription: string;
  envVars: Record<string, string>;
  onChangeName: (value: string) => void;
  onChangeDescription: (value: string) => void;
  onChangeEnvVar: (name: string, value: string) => void;
  errors?: Record<string, string[] | string | undefined>;
  disabled?: boolean;
  // Built-in actions
  onValidate?: () => void;
  onForceCreate?: () => void;
  submitDisabled?: boolean;
  validateDisabled?: boolean;
  validateLoading?: boolean;
  forceCreateDisabled?: boolean;
  submitLabel?: string;
  forceCreateLabel?: string;
  validateLabel?: string;
  // Optional extra actions (e.g., Cancel)
  extraActions?: React.ReactNode;
  // Form handling
  formAction?: string | ((formData: FormData) => void | Promise<void>);
  onSubmit?: (e?: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
  formId?: string;
  className?: string;
  contentClassName?: string;
  hideSubmitButton?: boolean;
  hideForceCreateButton?: boolean;
  // Optional container summary
  showContainerSummary?: boolean;
  containerImage?: string;
  containerPort?: number;
  // Rendering mode
  renderAsForm?: boolean;
}

export default function MCPInstanceConfigForm({
  server,
  instanceName,
  instanceDescription,
  envVars,
  onChangeName,
  onChangeDescription,
  onChangeEnvVar,
  errors,
  disabled = false,
  onValidate,
  onForceCreate,
  submitDisabled,
  validateDisabled,
  validateLoading = false,
  forceCreateDisabled,
  submitLabel,
  forceCreateLabel,
  validateLabel,
  extraActions,
  formAction,
  onSubmit,
  formId,
  className,
  contentClassName,
  hideSubmitButton = false,
  hideForceCreateButton = false,
  showContainerSummary = true,
  containerImage,
  containerPort,
  renderAsForm = true,
}: MCPInstanceConfigFormProps) {
  const t = useTranslations("MCPServersPage.instanceForm");
  const envSchema = Array.isArray(server?.env_schema) ? server.env_schema : [];

  const getErrorText = (key: string): string | undefined => {
    const err = errors?.[key];
    if (!err) return undefined;
    if (Array.isArray(err)) return err[0];
    if (typeof err === "string") return err;
    return undefined;
  };

  const resolvedImage = containerImage ?? server?.docker_image_url ?? "";
  const resolvedPort = containerPort ?? 8000;
  const resolvedSubmitLabel = submitLabel ?? t("actions.createInstance");
  const resolvedForceCreateLabel = forceCreateLabel ?? t("actions.forceCreate");
  const resolvedValidateLabel = validateLabel ?? t("actions.validate");

  const Content = (
    <div
      className={cn(
        "form-content flex flex-col overflow-y-auto pb-4",
        contentClassName
      )}
    >
      <div className="grid gap-4">
        <div className="grid gap-2">
          <FormLabel htmlFor="name" icon={Server}>
            {t("name")}
          </FormLabel>
          <Input
            id="name"
            name="name"
            placeholder={t("namePlaceholder")}
            value={instanceName}
            onChange={(e) => onChangeName(e.target.value)}
            required
            disabled={disabled}
            className={getErrorText("name") ? "border-red-500" : ""}
          />
          {getErrorText("name") && (
            <p className="form-error">{getErrorText("name")}</p>
          )}
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="description" icon={FileText} optional>
            {t("description")}
          </FormLabel>
          <Textarea
            id="description"
            name="description"
            placeholder={t("descriptionPlaceholder")}
            value={instanceDescription}
            onChange={(e) => onChangeDescription(e.target.value)}
            rows={2}
            disabled={disabled}
          />
        </div>
      </div>

      {envSchema && envSchema.length > 0 && (
        <div className="grid gap-4">
          <div className="flex items-center gap-2">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("envVarsTitle")}
            </div>
            <TooltipProvider>
              <Tooltip delayDuration={300}>
                <TooltipTrigger asChild>
                  <Info className="h-3.5 w-3.5 text-muted-foreground transition-colors duration-300 hover:text-primary" />
                </TooltipTrigger>
                <TooltipContent className="max-w-xs text-xs">
                  {t("envVarsTooltip")}
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <div className="grid gap-4">
            {envSchema.map((envVar: { [key: string]: unknown }) => {
              const envName = (envVar?.name as string) || "";
              if (!envName) return null;
              const isRequired = Boolean(envVar?.required);
              const description = (envVar?.description as string) || "";
              const errorKey = `env_${envName}`;
              return (
                <div key={envName} className="grid gap-2">
                  <div className="flex items-center gap-2">
                    <FormLabel htmlFor={`env_${envName}`}>
                      {envName}
                    </FormLabel>
                    {isRequired && (
                      <span className="rounded bg-red-100 px-1 text-[10px] text-red-700">
                        {t("required")}
                      </span>
                    )}
                  </div>
                  <Input
                    id={`env_${envName}`}
                    name={`env_${envName}`}
                    type={envVar?.isSecret ? "password" : "text"}
                    placeholder={envVar?.default || t("envVarPlaceholder", { name: envName })}
                    value={envVars[envName] || ""}
                    onChange={(e) => onChangeEnvVar(envName, e.target.value)}
                    disabled={disabled}
                    required={isRequired}
                    className={
                      (isRequired && !envVars[envName]?.trim()) ||
                      getErrorText(errorKey)
                        ? "border-red-300"
                        : ""
                    }
                  />
                  {description && (
                    <p className="note">{description}</p>
                  )}
                  {getErrorText(errorKey) && (
                    <p className="form-error">{getErrorText(errorKey)}</p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {onValidate && (
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("validationTitle")}
          </div>
          <Button
            variant="outline"
            size="xs"
            type="button"
            onClick={onValidate}
            disabled={!!validateDisabled}
            isLoading={validateLoading}
          >
            {!validateLoading && <ShieldCheck />}
            {resolvedValidateLabel}
          </Button>
        </div>
      )}

      {showContainerSummary && (
        <div className="grid gap-2">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("containerTitle")}
          </div>
          <div className="space-y-1 rounded-lg border border-border/60 bg-muted/40 p-3 dark:border-zinc-700/60 dark:bg-zinc-900/60">
            <div className="text-xs">
              <span className="font-medium">{t("image")}:</span> {resolvedImage}
            </div>
            <div className="text-xs">
              <span className="font-medium">{t("port")}:</span> {resolvedPort}
            </div>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
        {onForceCreate && !hideForceCreateButton && (
          <Button
            variant="destructive"
            type="button"
            onClick={onForceCreate}
            disabled={!!forceCreateDisabled}
          >
            {resolvedForceCreateLabel}
          </Button>
        )}
        {!hideSubmitButton &&
          (renderAsForm ? (
            <Button type="submit" disabled={!!submitDisabled}>
              {resolvedSubmitLabel}
            </Button>
          ) : (
            <Button
              type="button"
              disabled={!!submitDisabled}
              onClick={() => onSubmit && onSubmit()}
            >
              {resolvedSubmitLabel}
            </Button>
          ))}
        {extraActions}
      </div>
    </div>
  );

  if (renderAsForm) {
    return (
      <form id={formId} action={formAction} onSubmit={onSubmit} className={className}>
        {Content}
      </form>
    );
  }

  return Content;
}

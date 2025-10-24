"use client";

import React from "react";
import { Info } from "lucide-react";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";

type MCPServer = components["schemas"]["MCPServerResponse"];

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
  forceCreateDisabled?: boolean;
  submitLabel?: string;
  forceCreateLabel?: string;
  validateLabel?: string;
  // Optional extra actions (e.g., Cancel)
  extraActions?: React.ReactNode;
  // Form handling
  formAction?: any; // server action binding
  onSubmit?: (e?: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
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
  forceCreateDisabled,
  submitLabel = "Create Instance",
  forceCreateLabel = "Force Create",
  validateLabel = "Validate",
  extraActions,
  formAction,
  onSubmit,
  showContainerSummary = true,
  containerImage,
  containerPort,
  renderAsForm = true,
}: MCPInstanceConfigFormProps) {
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

  const Content = (
    <div className="flex flex-col gap-4 overflow-y-auto pb-4">
      <div className="space-y-3">
        <div>
          <Label htmlFor="name">Name</Label>
          <Input
            id="name"
            name="name"
            placeholder="Enter instance name"
            value={instanceName}
            onChange={(e) => onChangeName(e.target.value)}
            required
            disabled={disabled}
            className={getErrorText("name") ? "border-red-500" : ""}
          />
          {getErrorText("name") && (
            <p className="mt-1 text-sm text-red-500">{getErrorText("name")}</p>
          )}
        </div>
        <div>
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            name="description"
            placeholder="Enter instance description"
            value={instanceDescription}
            onChange={(e) => onChangeDescription(e.target.value)}
            rows={2}
            disabled={disabled}
          />
        </div>
      </div>

      {envSchema && envSchema.length > 0 && (
        <>
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium">Environment Variables</h4>
              <Info className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="space-y-3">
              {envSchema.map((envVar: any) => {
                const envName = (envVar?.name as string) || "";
                if (!envName) return null;
                const isRequired = Boolean(envVar?.required);
                const description = (envVar?.description as string) || "";
                const errorKey = `env_${envName}`;
                return (
                  <div key={envName} className="space-y-2">
                    <div className="flex items-center gap-2">
                      <Label
                        htmlFor={`env_${envName}`}
                        className="text-sm font-medium"
                      >
                        {envName}
                      </Label>
                      {isRequired && (
                        <span className="rounded bg-red-100 px-1 text-[10px] text-red-700">
                          Required
                        </span>
                      )}
                    </div>
                    <Input
                      id={`env_${envName}`}
                      name={`env_${envName}`}
                      placeholder={envVar?.default || `Enter ${envName}`}
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
                      <p className="text-xs text-muted-foreground">
                        {description}
                      </p>
                    )}
                    {getErrorText(errorKey) && (
                      <p className="text-xs text-red-500">
                        {getErrorText(errorKey)}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {onValidate && (
        <>
          <Separator />
          <div className="flex items-center gap-2">
            <h4 className="text-sm font-medium">Configuration Validation</h4>
            <Button
              variant="outline"
              type="button"
              onClick={onValidate}
              disabled={!!validateDisabled}
            >
              {validateLabel}
            </Button>
          </div>
        </>
      )}

      {showContainerSummary && (
        <>
          <Separator />
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Container Configuration</h4>
            <div className="space-y-1 rounded-lg bg-muted/50 p-3">
              <div className="text-xs">
                <span className="font-medium">Image:</span> {resolvedImage}
              </div>
              <div className="text-xs">
                <span className="font-medium">Port:</span> {resolvedPort}
              </div>
            </div>
          </div>
        </>
      )}

      <Separator />
      <div className="flex flex-wrap items-center justify-end gap-2">
        {onForceCreate && (
          <Button
            variant="destructive"
            type="button"
            onClick={onForceCreate}
            disabled={!!forceCreateDisabled}
          >
            {forceCreateLabel}
          </Button>
        )}
        {renderAsForm ? (
          <Button type="submit" disabled={!!submitDisabled}>
            {submitLabel}
          </Button>
        ) : (
          <Button
            type="button"
            disabled={!!submitDisabled}
            onClick={() => onSubmit && onSubmit()}
          >
            {submitLabel}
          </Button>
        )}
        {extraActions}
      </div>
    </div>
  );

  if (renderAsForm) {
    return (
      <form action={formAction} onSubmit={onSubmit}>
        {Content}
      </form>
    );
  }

  return Content;
}

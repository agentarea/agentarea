"use client";

import { Suspense, use, useState } from "react";
import { useTranslations } from "next-intl";
import {
  FileText,
  FolderGit2,
  GitBranch,
  KeyRound,
  Link2,
  Loader2,
  Package,
  ShieldCheck,
  Tag,
  Warehouse,
} from "lucide-react";
import { Controller, useForm, useWatch, type Control } from "react-hook-form";
import FormLabel from "@/components/FormLabel/FormLabel";
import { useRegistryTrustLabel } from "@/components/RegistryBadge";
import { SecretSelect, type SelectableSecret } from "@/components/SecretSelect";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { createRegistryAction, updateRegistryAction } from "./actions";
import {
  emptyRegistryForm,
  mustMirror,
  REGISTRY_MODES,
  REGISTRY_TYPES,
  SOURCE_TYPES,
  WORKSPACE_TRUST_LEVELS,
  type RegistryFormValues,
} from "./registry-form";

export type RegistryDialogTarget =
  | { mode: "create" }
  | { mode: "edit"; registryId: string; values: RegistryFormValues };

function FieldError({ message }: { message?: string }) {
  return message ? (
    <p className="form-error" role="alert">
      {message}
    </p>
  ) : null;
}

/** The secret picker, once the workspace's secrets have loaded. */
function CredentialsField({
  secrets,
  control,
  disabled,
}: {
  secrets: Promise<SelectableSecret[]>;
  control: Control<RegistryFormValues>;
  disabled: boolean;
}) {
  const t = useTranslations("Registries.form");
  const options = use(secrets);
  return (
    <Controller
      control={control}
      name="credentials_secret_id"
      render={({ field }) => (
        <div className="flex items-center gap-2">
          <SecretSelect
            id="registry-credentials"
            secrets={options}
            value={field.value}
            onChange={field.onChange}
            disabled={disabled}
            placeholder={t("credentialsNone")}
            searchPlaceholder={t("credentialsSearch")}
            emptyMessage={t("credentialsEmpty")}
            createLabel={t("credentialsCreate")}
          />
          {field.value && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => field.onChange("")}
              disabled={disabled}
            >
              {t("credentialsClear")}
            </Button>
          )}
        </div>
      )}
    />
  );
}

/**
 * Add a workspace registry, or edit one. Mount with a fresh `key` per opening
 * so a reopened dialog starts from its target's values.
 */
export default function RegistryFormDialog({
  target,
  secrets,
  open,
  onOpenChange,
}: {
  target: RegistryDialogTarget;
  secrets: Promise<SelectableSecret[]>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("Registries.form");
  const trustLabel = useRegistryTrustLabel();
  const isEdit = target.mode === "edit";
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegistryFormValues>({
    defaultValues: isEdit ? target.values : emptyRegistryForm(),
  });
  const sourceType = useWatch({ control, name: "source_type" });
  const registryType = useWatch({ control, name: "registry_type" });
  const credentials = useWatch({ control, name: "credentials_secret_id" });
  const lockedToMirror = mustMirror({
    registry_type: registryType,
    credentials_secret_id: credentials,
  });
  const isGithub = sourceType === "github";

  const onSubmit = async (values: RegistryFormValues) => {
    setSubmitError(null);
    try {
      const result = isEdit
        ? await updateRegistryAction(target.registryId, values)
        : await createRegistryAction(values);
      if (!result.ok) {
        for (const [field, message] of Object.entries(result.errors ?? {})) {
          if (field in values) {
            setError(field as keyof RegistryFormValues, { message });
          }
        }
        setSubmitError(result.message);
        return;
      }
      onOpenChange(false);
    } catch (error) {
      console.error("Failed to save registry", error);
      setSubmitError(isEdit ? t("updateFailed") : t("createFailed"));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isSubmitting) onOpenChange(next);
      }}
    >
      <BlueprintDialogContent
        title={isEdit ? t("editTitle") : t("createTitle")}
        description={t("description")}
        actions={
          <Button
            size="sm"
            type="submit"
            form="registry-form"
            disabled={isSubmitting}
          >
            {isSubmitting && <Loader2 className="animate-spin" />}
            {isEdit ? t("save") : t("create")}
          </Button>
        }
      >
        <form id="registry-form" onSubmit={handleSubmit(onSubmit)}>
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="registry-name" icon={Tag} required>
                {t("name")}
              </FormLabel>
              <Input
                id="registry-name"
                autoComplete="off"
                placeholder={t("namePlaceholder")}
                disabled={isSubmitting}
                {...register("name", {
                  validate: (v) => v.trim().length > 0 || t("nameRequired"),
                })}
              />
              <FieldError message={errors.name?.message} />
            </div>

            <div className="space-y-2">
              <FormLabel
                htmlFor="registry-description"
                icon={FileText}
                optional
              >
                {t("descriptionLabel")}
              </FormLabel>
              <Input
                id="registry-description"
                autoComplete="off"
                disabled={isSubmitting}
                {...register("description")}
              />
            </div>

            <div className="space-y-2">
              <FormLabel icon={FolderGit2}>{t("sourceType")}</FormLabel>
              {isEdit ? (
                <p className="text-sm text-muted-foreground">
                  {t(`sourceTypes.${sourceType}`)}
                </p>
              ) : (
                <Controller
                  control={control}
                  name="source_type"
                  render={({ field }) => (
                    <SegmentedControl
                      layoutId="registry-source-type"
                      value={field.value}
                      onChange={field.onChange}
                      items={SOURCE_TYPES.map((value) => ({
                        value,
                        label: t(`sourceTypes.${value}`),
                      }))}
                    />
                  )}
                />
              )}
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="registry-source" icon={Link2} required>
                {isGithub ? t("repository") : t("indexUrl")}
              </FormLabel>
              <Input
                id="registry-source"
                autoComplete="off"
                placeholder={
                  isGithub
                    ? t("repositoryPlaceholder")
                    : t("indexUrlPlaceholder")
                }
                disabled={isSubmitting}
                {...register("source_url", {
                  validate: (v) => v.trim().length > 0 || t("sourceRequired"),
                })}
              />
              <FieldError message={errors.source_url?.message} />
            </div>

            {isGithub && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <FormLabel htmlFor="registry-ref" icon={GitBranch} optional>
                    {t("ref")}
                  </FormLabel>
                  <Input
                    id="registry-ref"
                    autoComplete="off"
                    placeholder={t("refPlaceholder")}
                    disabled={isSubmitting}
                    {...register("source_ref")}
                  />
                  <FieldError message={errors.source_ref?.message} />
                </div>
                <div className="space-y-2">
                  <FormLabel htmlFor="registry-path" icon={FolderGit2} optional>
                    {t("path")}
                  </FormLabel>
                  <Input
                    id="registry-path"
                    autoComplete="off"
                    placeholder={t("pathPlaceholder")}
                    disabled={isSubmitting}
                    {...register("source_path")}
                  />
                </div>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <FormLabel htmlFor="registry-type" icon={Package}>
                  {t("registryType")}
                </FormLabel>
                <Controller
                  control={control}
                  name="registry_type"
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={isEdit || isSubmitting}
                    >
                      <SelectTrigger id="registry-type">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {REGISTRY_TYPES.map((value) => (
                          <SelectItem key={value} value={value}>
                            {t(`registryTypes.${value}`)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              <div className="space-y-2">
                <FormLabel htmlFor="registry-trust" icon={ShieldCheck}>
                  {t("trust")}
                </FormLabel>
                <Controller
                  control={control}
                  name="trust"
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={field.onChange}
                      disabled={isSubmitting}
                    >
                      <SelectTrigger id="registry-trust">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {WORKSPACE_TRUST_LEVELS.map((value) => (
                          <SelectItem key={value} value={value}>
                            {trustLabel(value)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="registry-mode" icon={Warehouse}>
                {t("mode")}
              </FormLabel>
              <Controller
                control={control}
                name="mode"
                render={({ field }) => (
                  <Select
                    value={lockedToMirror ? "mirror" : field.value}
                    onValueChange={field.onChange}
                    disabled={isSubmitting}
                  >
                    <SelectTrigger id="registry-mode">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {REGISTRY_MODES.map((value) => (
                        <SelectItem
                          key={value}
                          value={value}
                          disabled={lockedToMirror && value !== "mirror"}
                        >
                          {t(`modes.${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              />
              <p className="text-xs text-muted-foreground">
                {lockedToMirror ? t("modeLocked") : t("modeHint")}
              </p>
            </div>

            <div className="space-y-2">
              <FormLabel
                htmlFor="registry-credentials"
                icon={KeyRound}
                optional
              >
                {t("credentials")}
              </FormLabel>
              <Suspense
                fallback={
                  <SecretSelect
                    secrets={[]}
                    value=""
                    onChange={() => undefined}
                    disabled
                    placeholder={t("credentialsLoading")}
                    searchPlaceholder={t("credentialsSearch")}
                    emptyMessage={t("credentialsEmpty")}
                    createLabel={t("credentialsCreate")}
                  />
                }
              >
                <CredentialsField
                  secrets={secrets}
                  control={control}
                  disabled={isSubmitting}
                />
              </Suspense>
              <p className="text-xs text-muted-foreground">
                {t("credentialsHint")}
              </p>
            </div>

            {isEdit && (
              <div className="flex items-center justify-between gap-3">
                <FormLabel htmlFor="registry-active">{t("active")}</FormLabel>
                <Controller
                  control={control}
                  name="is_active"
                  render={({ field }) => (
                    <Switch
                      id="registry-active"
                      checked={field.value}
                      onCheckedChange={field.onChange}
                      disabled={isSubmitting}
                    />
                  )}
                />
              </div>
            )}

            {submitError && (
              <p className="form-error" role="alert">
                {submitError}
              </p>
            )}
          </BlueprintFields>
        </form>
      </BlueprintDialogContent>
    </Dialog>
  );
}

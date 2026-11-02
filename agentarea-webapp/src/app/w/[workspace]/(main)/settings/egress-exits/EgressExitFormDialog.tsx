"use client";

import { Suspense, use, useState } from "react";
import { useTranslations } from "next-intl";
import { FileText, Globe, KeyRound, Loader2, Tag, User } from "lucide-react";
import { Controller, useForm, useWatch, type Control } from "react-hook-form";
import FieldError from "@/components/FieldError";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SecretSelect, type SelectableSecret } from "@/components/SecretSelect";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { createEgressExitAction, updateEgressExitAction } from "./actions";
import {
  emptyEgressExitForm,
  sendsPlaintextCredentials,
  type EgressExitFormValues,
} from "./egress-exit-form";

export type EgressExitDialogTarget =
  | { mode: "create" }
  | { mode: "edit"; exitId: string; values: EgressExitFormValues };

/** The workspace's secrets the password may be read from, or why they did not load. */
export type SecretChoices =
  | { ok: true; secrets: SelectableSecret[] }
  | { ok: false; message: string };

/** The secret picker, once the workspace's secrets have loaded. */
function PasswordField({
  secrets,
  control,
  disabled,
}: {
  secrets: Promise<SecretChoices>;
  control: Control<EgressExitFormValues>;
  disabled: boolean;
}) {
  const t = useTranslations("EgressExits.form");
  const choices = use(secrets);
  if (!choices.ok) return <FormError>{choices.message}</FormError>;
  return (
    <Controller
      control={control}
      name="password_secret_id"
      render={({ field }) => (
        <div className="flex items-center gap-2">
          <SecretSelect
            id="egress-exit-password"
            secrets={choices.secrets}
            value={field.value}
            onChange={field.onChange}
            disabled={disabled}
            placeholder={t("passwordNone")}
            searchPlaceholder={t("passwordSearch")}
            emptyMessage={t("passwordEmpty")}
            createLabel={t("passwordCreate")}
          />
          {field.value && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => field.onChange("")}
              disabled={disabled}
            >
              {t("passwordClear")}
            </Button>
          )}
        </div>
      )}
    />
  );
}

/**
 * Add an exit of the workspace, or edit one. Mount with a fresh `key` per
 * opening so a reopened dialog starts from its target's values.
 */
export default function EgressExitFormDialog({
  target,
  secrets,
  open,
  onOpenChange,
}: {
  target: EgressExitDialogTarget;
  secrets: Promise<SecretChoices>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("EgressExits.form");
  const isEdit = target.mode === "edit";
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    control,
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<EgressExitFormValues>({
    defaultValues: isEdit ? target.values : emptyEgressExitForm(),
  });
  const upstreamUrl = useWatch({ control, name: "upstream_url" });
  const username = useWatch({ control, name: "username" });
  const plaintext = sendsPlaintextCredentials({
    upstream_url: upstreamUrl,
    username,
  });

  const onSubmit = async (values: EgressExitFormValues) => {
    setSubmitError(null);
    try {
      const result = isEdit
        ? await updateEgressExitAction(target.exitId, values)
        : await createEgressExitAction(values);
      if (!result.ok) {
        for (const [field, message] of Object.entries(result.errors ?? {})) {
          if (field in values) {
            setError(field as keyof EgressExitFormValues, { message });
          }
        }
        setSubmitError(result.message);
        return;
      }
      onOpenChange(false);
    } catch (error) {
      console.error("Failed to save egress exit", error);
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
            form="egress-exit-form"
            disabled={isSubmitting}
          >
            {isSubmitting && <Loader2 className="animate-spin" />}
            {isEdit ? t("save") : t("create")}
          </Button>
        }
      >
        <form id="egress-exit-form" onSubmit={handleSubmit(onSubmit)}>
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="egress-exit-name" icon={Tag} required>
                {t("name")}
              </FormLabel>
              <Input
                id="egress-exit-name"
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
                htmlFor="egress-exit-description"
                icon={FileText}
                optional
              >
                {t("descriptionLabel")}
              </FormLabel>
              <Input
                id="egress-exit-description"
                autoComplete="off"
                disabled={isSubmitting}
                {...register("description")}
              />
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="egress-exit-upstream" icon={Globe} required>
                {t("upstreamUrl")}
              </FormLabel>
              <Input
                id="egress-exit-upstream"
                autoComplete="off"
                className="font-mono"
                placeholder="https://proxy.example.com:8443"
                disabled={isSubmitting}
                {...register("upstream_url", {
                  validate: (v) =>
                    v.trim().length > 0 || t("upstreamUrlRequired"),
                })}
              />
              <p className="text-xs text-muted-foreground">
                {t("upstreamUrlHint")}
              </p>
              <FieldError message={errors.upstream_url?.message} />
            </div>

            <div className="space-y-2">
              <FormLabel htmlFor="egress-exit-username" icon={User} optional>
                {t("username")}
              </FormLabel>
              <Input
                id="egress-exit-username"
                autoComplete="off"
                disabled={isSubmitting}
                {...register("username")}
              />
              <FieldError message={errors.username?.message} />
            </div>

            <div className="space-y-2">
              <FormLabel
                htmlFor="egress-exit-password"
                icon={KeyRound}
                optional
              >
                {t("password")}
              </FormLabel>
              <Suspense
                fallback={
                  <SecretSelect
                    secrets={[]}
                    value=""
                    onChange={() => undefined}
                    disabled
                    placeholder={t("passwordLoading")}
                    searchPlaceholder={t("passwordSearch")}
                    emptyMessage={t("passwordEmpty")}
                    createLabel={t("passwordCreate")}
                  />
                }
              >
                <PasswordField
                  secrets={secrets}
                  control={control}
                  disabled={isSubmitting}
                />
              </Suspense>
              <p className="text-xs text-muted-foreground">
                {t("passwordHint")}
              </p>
              <FieldError message={errors.password_secret_id?.message} />
            </div>

            {plaintext && (
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                  <FormLabel htmlFor="egress-exit-plaintext">
                    {t("allowPlaintext")}
                  </FormLabel>
                  <Controller
                    control={control}
                    name="allow_plaintext_credentials"
                    render={({ field }) => (
                      <Switch
                        id="egress-exit-plaintext"
                        checked={field.value}
                        onCheckedChange={field.onChange}
                        disabled={isSubmitting}
                      />
                    )}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("allowPlaintextHint")}
                </p>
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

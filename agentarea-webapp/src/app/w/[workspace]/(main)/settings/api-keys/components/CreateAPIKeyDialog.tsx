"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { Clock, Key, Loader2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import type {
  ApiKeyCreateRequest,
  ApiKeyCreateResponse,
} from "@/api/client/types.gen";
import { zApiKeyCreateRequest } from "@/api/client/zod.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  OneTimeSecretField,
  SuccessModalContent,
  SuccessModalDetail,
} from "@/components/SuccessModal";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { formatDate } from "@/utils/dateUtils";
import { createAPIKeyAction } from "../actions";

interface CreateAPIKeyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Create form, then — in the same dialog — the new key, shown once. Mount it
 * with a fresh `key` per opening so a reopened dialog starts on the form.
 */
export default function CreateAPIKeyDialog({
  open,
  onOpenChange,
}: CreateAPIKeyDialogProps) {
  const t = useTranslations("APIKeysPage");
  const locale = useLocale();
  const router = useWorkspaceRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreateResponse | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ApiKeyCreateRequest>({
    resolver: zodResolver(zApiKeyCreateRequest),
    defaultValues: {
      name: "",
      expires_in_days: undefined,
    },
  });

  const onSubmit = async (data: ApiKeyCreateRequest) => {
    setIsSubmitting(true);

    try {
      const result = await createAPIKeyAction({
        ...data,
        name: data.name.trim(),
      });

      if (result.error) {
        toast.error(t("error.createFailed"), { description: result.error });
        return;
      }

      setCreated(result.data as ApiKeyCreateResponse);
      router.refresh();
    } catch (_error) {
      toast.error(t("error.createFailed"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      reset();
      onOpenChange(false);
    }
  };

  if (created) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <SuccessModalContent
          title={t("created.title")}
          description={t("created.description", { name: created.name })}
          doneLabel={t("created.done")}
          onDone={() => onOpenChange(false)}
        >
          <OneTimeSecretField
            label={t("created.keyLabel")}
            icon={Key}
            value={created.token}
            warning={t("created.warning")}
          />
          <SuccessModalDetail label={t("table.expires")} icon={Clock}>
            {created.expires_at
              ? formatDate(created.expires_at, locale)
              : t("never")}
          </SuccessModalDetail>
        </SuccessModalContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <BlueprintDialogContent
        title={t("create.title")}
        description={t("create.description")}
        actions={
          <Button
            size="sm"
            type="submit"
            form="api-key-form"
            disabled={isSubmitting}
          >
            {isSubmitting && <Loader2 className="animate-spin" />}
            {t("create.createButton")}
          </Button>
        }
      >
        <form id="api-key-form" onSubmit={handleSubmit(onSubmit)}>
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="api-key-name" icon={Key} required>
                {t("create.name")}
              </FormLabel>
              <Input
                id="api-key-name"
                autoComplete="off"
                placeholder={t("create.namePlaceholder")}
                {...register("name")}
                required
                disabled={isSubmitting}
              />
              {errors.name && (
                <p className="form-error" role="alert">
                  {errors.name.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <FormLabel htmlFor="api-key-expiry" icon={Clock} optional>
                {t("create.expiresInDays")}
              </FormLabel>
              <Input
                id="api-key-expiry"
                type="number"
                placeholder={t("create.expiresInDaysPlaceholder")}
                {...register("expires_in_days", {
                  setValueAs: (value) =>
                    value === "" || value == null ? undefined : Number(value),
                })}
                min="1"
                disabled={isSubmitting}
              />
              {errors.expires_in_days && (
                <p className="form-error" role="alert">
                  {errors.expires_in_days.message}
                </p>
              )}
            </div>
          </BlueprintFields>
        </form>
      </BlueprintDialogContent>
    </Dialog>
  );
}

"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { Calendar, Clock, Key } from "lucide-react";
import { useForm } from "react-hook-form";
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
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
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
  const router = useRouter();
  const { toast } = useToast();
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
        toast({
          title: t("error.createFailed"),
          description: result.error,
          variant: "destructive",
        });
        setIsSubmitting(false);
        return;
      }

      setCreated(result.data as ApiKeyCreateResponse);
      router.refresh();
    } catch (_error) {
      toast({
        title: t("error.createFailed"),
        variant: "destructive",
      });
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
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>{t("create.description")}</DialogDescription>
        </DialogHeader>
        <form id="api-key-form" onSubmit={handleSubmit(onSubmit)}>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <FormLabel htmlFor="api-key-name" icon={Key} required>
                {t("create.name")}
              </FormLabel>
              <Input
                id="api-key-name"
                placeholder={t("create.namePlaceholder")}
                {...register("name")}
                required
                disabled={isSubmitting}
              />
              {errors.name && (
                <p className="form-error">{errors.name.message}</p>
              )}
            </div>

            <div className="grid gap-2">
              <FormLabel
                htmlFor="api-key-expiry"
                icon={Calendar}
                required={false}
              >
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
                <p className="form-error">{errors.expires_in_days.message}</p>
              )}
            </div>
          </div>
        </form>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={handleClose}
            disabled={isSubmitting}
          >
            {t("create.cancel")}
          </Button>
          <Button type="submit" form="api-key-form" disabled={isSubmitting}>
            {isSubmitting ? t("create.creating") : t("create.createButton")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

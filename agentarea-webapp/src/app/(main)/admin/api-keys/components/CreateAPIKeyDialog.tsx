"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Calendar, Key } from "lucide-react";
import { useForm } from "react-hook-form";
import type { ApiKeyCreateRequest, ApiKeyCreateResponse } from "@/api/client/types.gen";
import { zApiKeyCreateRequest } from "@/api/client/zod.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
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
import { createAPIKeyAction } from "../actions";

interface CreateAPIKeyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: (token?: string) => void;
}

export default function CreateAPIKeyDialog({
  open,
  onOpenChange,
  onSuccess,
}: CreateAPIKeyDialogProps) {
  const t = useTranslations("APIKeysPage");
  const { toast } = useToast();
  const [isSubmitting, setIsSubmitting] = useState(false);

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

      const token = (result.data as ApiKeyCreateResponse)?.token;

      reset();
      onOpenChange(false);
      onSuccess?.(token);
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

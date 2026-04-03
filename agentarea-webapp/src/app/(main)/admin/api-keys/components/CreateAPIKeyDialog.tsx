"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { Calendar, Key } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
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

const apiKeySchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(255, "Name must be less than 255 characters"),
  expires_in_days: z
    .string()
    .optional()
    .refine(
      (val) => !val || (!isNaN(parseInt(val, 10)) && parseInt(val, 10) > 0),
      {
        message: "Must be a positive number",
      }
    ),
});

type APIKeyFormData = z.infer<typeof apiKeySchema>;

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
  } = useForm<APIKeyFormData>({
    resolver: zodResolver(apiKeySchema),
    defaultValues: {
      name: "",
      expires_in_days: "",
    },
  });

  const onSubmit = async (data: APIKeyFormData) => {
    setIsSubmitting(true);

    try {
      const formData = new FormData();
      formData.set("name", data.name.trim());
      if (data.expires_in_days) {
        formData.set("expires_in_days", data.expires_in_days);
      }

      const result = await createAPIKeyAction(formData);

      if (result.error) {
        toast({
          title: t("error.createFailed"),
          description: result.error,
          variant: "destructive",
        });
        setIsSubmitting(false);
        return;
      }

      const token = (result.data as any)?.token;

      reset();
      onOpenChange(false);
      onSuccess?.(token);
    } catch (error) {
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
                {...register("expires_in_days")}
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

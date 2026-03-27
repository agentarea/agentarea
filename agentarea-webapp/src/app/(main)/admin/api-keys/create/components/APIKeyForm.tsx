"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { Calendar, Key } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { createAPIKeyAction } from "../../actions";

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

export default function APIKeyForm() {
  const t = useTranslations("APIKeysPage");
  const { toast } = useToast();
  const router = useRouter();
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
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
      if (token) {
        router.push(`/admin/api-keys?new_token=${encodeURIComponent(token)}`);
      } else {
        router.push("/admin/api-keys");
      }
    } catch (error) {
      toast({
        title: t("error.createFailed"),
        variant: "destructive",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form
      id="api-key-form"
      onSubmit={handleSubmit(onSubmit)}
      className="form-content"
    >
      <div className="mx-auto max-w-xl">
        <div className="grid gap-4">
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
            {errors.name && <p className="form-error">{errors.name.message}</p>}
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
      </div>
    </form>
  );
}

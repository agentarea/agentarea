"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";
import { OPENAPI_FORM_ID } from "./form";

export default function AddOpenAPIHeaderControls() {
  const t = useTranslations("OpenAPIForm");
  const isSubmitting = useFormSubmittingState(OPENAPI_FORM_ID);

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        type="submit"
        form={OPENAPI_FORM_ID}
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        <Plus />
        {t("createConnection")}
      </Button>
    </div>
  );
}

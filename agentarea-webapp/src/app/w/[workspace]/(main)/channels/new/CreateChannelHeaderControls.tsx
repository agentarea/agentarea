"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";

export default function CreateChannelHeaderControls() {
  const t = useTranslations("ChannelsPage.create");
  const isSubmitting = useFormSubmittingState("create-channel-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        type="submit"
        form="create-channel-form"
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        <Plus />
        {t("submit")}
      </Button>
    </div>
  );
}

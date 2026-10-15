"use client";

import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import { Button } from "@/components/ui/button";

export default function CreateTriggerHeaderControls({
  label,
}: {
  label: string;
}) {
  const isSubmitting = useFormSubmittingState("create-trigger-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        type="submit"
        form="create-trigger-form"
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        {label}
      </Button>
    </div>
  );
}

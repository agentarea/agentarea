"use client";

import { Button } from "@/components/ui/button";
import { useFormSubmittingState } from "../shared/useFormSubmittingState";

export default function CreateAgentHeaderControls({
  label,
}: {
  label?: string;
}) {
  const isSubmitting = useFormSubmittingState();

  return (
    <div className="flex items-center gap-2 py-1">
      <Button size="xs" type="submit" form="agent-form" isLoading={isSubmitting}>
        {label}
      </Button>
    </div>
  );
}

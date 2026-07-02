"use client";

import { Button } from "@/components/ui/button";
import { useFormSubmittingState } from "@/app/(main)/agents/shared/useFormSubmittingState";

export default function AddMCPServerHeaderControls() {
  const isSubmitting = useFormSubmittingState("add-mcp-server-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button
        size="xs"
        type="submit"
        form="add-mcp-server-form"
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        Add Server
      </Button>
    </div>
  );
}

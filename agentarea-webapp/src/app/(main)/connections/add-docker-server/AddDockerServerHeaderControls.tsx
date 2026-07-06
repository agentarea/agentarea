"use client";

import { Button } from "@/components/ui/button";
import { useFormSubmittingState } from "@/app/(main)/agents/shared/useFormSubmittingState";

export default function AddDockerServerHeaderControls() {
  const isSubmitting = useFormSubmittingState("mcp-server-form");

  return (
    <div className="flex items-center gap-2 py-1">
      <Button 
        size="xs" 
        type="submit" 
        form="mcp-server-form" 
        isLoading={isSubmitting}
        disabled={isSubmitting}
      >
        Add Server
      </Button>
    </div>
  );
}


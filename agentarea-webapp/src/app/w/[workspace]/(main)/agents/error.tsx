"use client";

import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function AgentsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Agents Error]:", error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load agents"
      description="There was a problem loading your agents. This could be a temporary issue."
    />
  );
}

"use client";

import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function TasksError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Tasks Error]:", error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load tasks"
      description="There was a problem loading your tasks. This could be a temporary issue."
    />
  );
}

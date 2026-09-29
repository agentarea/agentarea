"use client";

import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function ProjectsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Projects Error]:", error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load projects"
      description="There was a problem loading your projects. Please try again."
    />
  );
}

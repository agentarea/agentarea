"use client";

import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function SkillsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Skills Error]:", error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load skills"
      description="There was a problem loading your skills. This could be a temporary issue."
    />
  );
}

"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function TriggersError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Triggers Error]:", error);
    // A digest means a server failure onRequestError already reported.
    if (!error.digest) Sentry.captureException(error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load triggers"
      description="There was a problem loading your automation triggers. Please try again."
    />
  );
}

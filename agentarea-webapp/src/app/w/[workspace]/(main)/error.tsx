"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function MainError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Main Layout Error]:", error);
    // A digest means a server failure onRequestError already reported.
    if (!error.digest) Sentry.captureException(error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Something went wrong"
      description="An error occurred while loading this page. Please try again."
      showHomeButton
    />
  );
}

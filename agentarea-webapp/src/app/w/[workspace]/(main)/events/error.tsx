"use client";

import { useEffect } from "react";
import * as Sentry from "@sentry/nextjs";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function EventsError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Events Error]:", error);
    // A digest means a server failure onRequestError already reported.
    if (!error.digest) Sentry.captureException(error);
  }, [error]);

  return (
    <ErrorFallback
      error={error}
      reset={reset}
      title="Failed to load events"
      description="There was a problem loading your event streams. Please try again."
    />
  );
}

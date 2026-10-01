"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";
import { ErrorFallback } from "@/components/ui/error-fallback";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[Global Error]:", error);
    // A digest means a server failure onRequestError already reported.
    if (!error.digest) Sentry.captureException(error);
  }, [error]);

  return (
    <html lang="en">
      <body className="bg-background">
        <ErrorFallback
          error={error}
          reset={reset}
          title="Application Error"
          description="A critical error occurred. Please refresh the page or try again."
          showHomeButton
          variant="full"
        />
      </body>
    </html>
  );
}

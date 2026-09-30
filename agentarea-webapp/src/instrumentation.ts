import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentry";

export function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    Sentry.init(
      sentryOptions(process.env.SENTRY_DSN, process.env.SENTRY_ENVIRONMENT)
    );
  }
}

// Server component, route handler and server action failures.
export const onRequestError = Sentry.captureRequestError;

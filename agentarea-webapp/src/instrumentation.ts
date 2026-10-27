import { PHASE_PRODUCTION_BUILD } from "next/constants";
import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentry";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    if (
      process.env.NODE_ENV === "production" &&
      process.env.NEXT_PHASE !== PHASE_PRODUCTION_BUILD
    ) {
      // Before Sentry.init, so Sentry's console breadcrumbs wrap the JSON
      // writer instead of being replaced by it.
      const { installJsonConsole } = await import("@/lib/json-console");
      installJsonConsole();
    }
    Sentry.init(
      sentryOptions(process.env.SENTRY_DSN, process.env.SENTRY_ENVIRONMENT)
    );
  }
}

// Server component, route handler and server action failures.
export const onRequestError = Sentry.captureRequestError;

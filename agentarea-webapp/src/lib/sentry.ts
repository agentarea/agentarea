import type { BrowserOptions, NodeOptions } from "@sentry/nextjs";
import { APP_VERSION } from "@/lib/app-version";

/**
 * The DSN arrives at runtime (SENTRY_DSN on the server, window.__ENV__ in the
 * browser), so one image serves every deployment; without one the SDK stays
 * off. Errors only, and none of the user, cookie, header, body or local
 * variable data the SDK collects by default.
 */
export function sentryOptions(
  dsn: string | undefined,
  environment: string | undefined
): BrowserOptions & NodeOptions {
  return {
    dsn: dsn || undefined,
    enabled: Boolean(dsn),
    environment: environment || undefined,
    release: APP_VERSION,
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: false,
      httpBodies: [],
      urlQueryParams: false,
      stackFrameVariables: false,
    },
  };
}

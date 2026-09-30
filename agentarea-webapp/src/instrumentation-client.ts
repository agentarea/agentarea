import * as Sentry from "@sentry/nextjs";
import { sentryOptions } from "@/lib/sentry";
import { SENTRY_TUNNEL_PATH } from "@/lib/sentry-tunnel";

// window.__ENV__ is written by an inline <head> script in the root layout,
// which runs before this bundle.
const runtimeEnv = (
  window as Window & {
    __ENV__?: { SENTRY_DSN?: string; SENTRY_ENVIRONMENT?: string };
  }
).__ENV__;

Sentry.init({
  ...sentryOptions(runtimeEnv?.SENTRY_DSN, runtimeEnv?.SENTRY_ENVIRONMENT),
  tunnel: SENTRY_TUNNEL_PATH,
});

import { getLocale } from "next-intl/server";
import type { OryClientConfiguration } from "@ory/elements-react";
import { env } from "@/env";
import config from "@/ory.config";

/**
 * Locales Ory Elements is translated into, i.e. the ones kept in
 * packages/elements-react/src/locales.
 */
const ORY_LOCALES = ["en", "ru"] as const;

/**
 * Returns Ory config with sdk.url set to the browser-accessible Kratos URL and
 * the UI locale matched to the one next-intl resolved for this request.
 *
 * In self-hosted setups, ORY_SDK_URL is the in-cluster URL (not reachable by browsers).
 * ORY_BROWSER_URL is the public URL browsers can reach (e.g. via Tailscale).
 * Setting sdk.url ensures @ory/elements-react renders links with the correct URL
 * during both SSR and client-side hydration.
 */
export async function getOryBrowserConfig(): Promise<OryClientConfiguration> {
  const browserUrl = process.env.ORY_BROWSER_URL || env.ORY_SDK_URL;
  const appLocale = await getLocale();
  const locale = (ORY_LOCALES as readonly string[]).includes(appLocale)
    ? appLocale
    : "en";

  return {
    ...config,
    sdk: {
      ...config.sdk,
      url: browserUrl,
    },
    intl: { locale },
    project: {
      ...config.project,
      default_locale: locale,
      enabled_locales: [...ORY_LOCALES],
    },
  };
}

/**
 * Deep-replace all occurrences of the in-cluster ORY_SDK_URL with the
 * browser-accessible URL in a flow object returned by Kratos.
 */
export function rewriteFlowForBrowser<T extends object>(flow: T): T {
  const browserUrl = process.env.ORY_BROWSER_URL;
  if (!browserUrl) return flow;

  const internalUrl = env.ORY_SDK_URL.replace(/\/$/, "");
  const publicUrl = browserUrl.replace(/\/$/, "");

  if (internalUrl === publicUrl) return flow;

  const json = JSON.stringify(flow);
  const rewritten = json.replaceAll(internalUrl, publicUrl);
  return JSON.parse(rewritten) as T;
}

import config from "@/ory.config";
import { env } from "@/env";

/**
 * Returns Ory config with sdk.url set to the browser-accessible Kratos URL.
 *
 * In self-hosted setups, ORY_SDK_URL is the in-cluster URL (not reachable by browsers).
 * BROWSER_ORY_SDK_URL is the public URL browsers can reach (e.g. via Tailscale).
 * Setting sdk.url ensures @ory/elements-react renders links with the correct URL
 * during both SSR and client-side hydration.
 */
export function getOryBrowserConfig() {
  const browserUrl = process.env.ORY_BROWSER_URL || env.ORY_SDK_URL;
  return {
    ...config,
    sdk: {
      ...config.sdk,
      url: browserUrl,
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

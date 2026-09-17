// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

/**
 * Resolves the Ory SDK base URL.
 *
 * On the server this is the in-cluster URL. In the browser it is the public URL
 * injected as `window.__ENV__.CLIENT_ORY_SDK_URL` by the root layout, because
 * the in-cluster URL is not reachable from a browser in self-hosted setups.
 */
export function orySdkUrl(): string {
  const baseUrl =
    (typeof window !== "undefined" &&
      (window as Window & { __ENV__?: { CLIENT_ORY_SDK_URL?: string } }).__ENV__
        ?.CLIENT_ORY_SDK_URL) ||
    process.env.ORY_SDK_URL;

  if (!baseUrl) {
    throw new Error(
      "ORY_SDK_URL is not set. The Ory SDK URL is required to render auth flows."
    );
  }

  return baseUrl.replace(/\/$/, "");
}

export function joinUrlPaths(baseUrl: string, relativeUrl: string): string {
  const base = new URL(baseUrl);
  const relative = new URL(relativeUrl, baseUrl);

  relative.pathname =
    base.pathname.replace(/\/$/, "") +
    "/" +
    relative.pathname.replace(/^\//, "");

  return new URL(relative.toString(), baseUrl).href;
}

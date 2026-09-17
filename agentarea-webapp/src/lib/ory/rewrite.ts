// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

import type { OryMiddlewareOptions } from "./types";
import { joinUrlPaths, orySdkUrl } from "./url";

export function rewriteUrls(
  source: string,
  matchBaseUrl: string,
  selfUrl: string,
  config: OryMiddlewareOptions
) {
  for (const [_, [matchPath, replaceWith]] of [
    // TODO load these dynamically from the project config

    // Old AX routes
    ["/ui/recovery", config.project?.recovery_ui_url],
    ["/ui/registration", config.project?.registration_ui_url],
    ["/ui/login", config.project?.login_ui_url],
    ["/ui/verification", config.project?.verification_ui_url],
    ["/ui/settings", config.project?.settings_ui_url],
    ["/ui/welcome", config.project?.default_redirect_url],

    // New AX routes
    ["/recovery", config.project?.recovery_ui_url],
    ["/registration", config.project?.registration_ui_url],
    ["/login", config.project?.login_ui_url],
    ["/verification", config.project?.verification_ui_url],
    ["/settings", config.project?.settings_ui_url],
  ].entries()) {
    const match = joinUrlPaths(matchBaseUrl, matchPath || "");
    if (replaceWith && source.startsWith(match)) {
      source = source.replaceAll(
        match,
        new URL(replaceWith, selfUrl).toString()
      );
    }
  }
  return source.replaceAll(
    matchBaseUrl.replace(/\/$/, ""),
    new URL(selfUrl).toString().replace(/\/$/, "")
  );
}

/**
 * Rewrites Ory SDK URLs in JSON responses (objects, arrays, strings) with the provided proxy URL.
 *
 * If `proxyUrl` is provided, the SDK URL is replaced with the proxy URL.
 */
export function rewriteJsonResponse<T extends object>(
  obj: T,
  proxyUrl?: string
): T {
  return Object.fromEntries(
    Object.entries(obj)
      .filter(([_, value]) => value !== undefined)
      .map(([key, value]) => {
        if (Array.isArray(value)) {
          return [
            key,
            value
              .map((item) => {
                if (typeof item === "object" && item !== null) {
                   
                  return rewriteJsonResponse(item, proxyUrl);
                } else if (typeof item === "string" && proxyUrl) {
                  return item.replaceAll(orySdkUrl(), proxyUrl);
                }
                 
                return item;
              })
              .filter((item) => item !== undefined),
          ];
        } else if (typeof value === "object" && value !== null) {
          return [key, rewriteJsonResponse(value, proxyUrl)];
        } else if (typeof value === "string" && proxyUrl) {
          return [key, value.replaceAll(orySdkUrl(), proxyUrl)];
        }
        return [key, value];
      })
  ) as T;
}

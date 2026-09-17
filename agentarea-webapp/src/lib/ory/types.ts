// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0), vendored into the app so the auth
// plumbing lives next to the auth pages that are its only consumer.

import type { AccountExperienceConfiguration } from "@ory/client-fetch";

export type QueryParams = { [key: string]: string | string[] | undefined };

export const initOverrides: RequestInit = {
  cache: "no-cache",
};

/**
 * The shape of an App Router page's props, which Next.js does not export.
 */
export interface OryPageParams {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export type OryMiddlewareOptions = {
  /**
   * By default headers are filtered to forward only a fixed list.
   *
   * If you need to forward additional headers you can use this setting to define them.
   */
  forwardAdditionalHeaders?: string[];
  /**
   * If you want to force a specific cookie domain, you can set it here.
   */
  forceCookieDomain?: string;
  /**
   * If you want to use a specific project configuration, you can set it here.
   *
   * Make sure to pass the same project configuration that you pass to `@ory/elements-react`
   */
  project?: Partial<AccountExperienceConfiguration>;
};

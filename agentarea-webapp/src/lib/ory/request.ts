// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

import type { ParsedUrlQuery } from "querystring";
import { headers } from "next/headers";
import { redirect, RedirectType } from "next/navigation";
import { FlowType, OnRedirectHandler } from "@ory/client-fetch";
import type { QueryParams } from "./types";

export async function getCookieHeader() {
  const h = await headers();
  return h.get("cookie") ?? undefined;
}

export const onRedirect: OnRedirectHandler = (url) => {
  redirect(url);
};

export async function toGetFlowParameter(
  params: Promise<QueryParams> | QueryParams
) {
  return {
    id: (await params)["flow"]?.toString() ?? "",
    cookie: await getCookieHeader(),
  };
}

export async function getPublicUrl() {
  const h = await headers();
  const host = h.get("host");
  const protocol = h.get("x-forwarded-proto") || "http";
  return `${protocol}://${host}`;
}

export function startNewFlow(
  params: QueryParams,
  flowType: FlowType,
  baseUrl: string
) {
  // Take advantage of the fact, that Ory handles the flow creation for us and redirects the user to the default
  // return to automatically if they're logged in already.
  return redirect(
    new URL(
      "/self-service/" +
        flowType.toString() +
        "/browser?" +
        urlQueryToSearchParams(params).toString(),
      baseUrl
    ).toString(),
    RedirectType.replace
  );
}

// Copied over from https://github.com/vercel/next.js/blob/dbd5e1b274d30f9107141475eba116a8118bc346/packages/next/src/shared/lib/router/utils/querystring.ts
// to avoid relying on internal APIs
function stringifyUrlQueryParam(param: unknown): string {
  if (typeof param === "string") {
    return param;
  }

  if (
    (typeof param === "number" && !isNaN(param)) ||
    typeof param === "boolean"
  ) {
    return String(param);
  } else {
    return "";
  }
}

export function urlQueryToSearchParams(query: ParsedUrlQuery): URLSearchParams {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        searchParams.append(key, stringifyUrlQueryParam(item));
      }
    } else {
      searchParams.set(key, stringifyUrlQueryParam(value));
    }
  }
  return searchParams;
}

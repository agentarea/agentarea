// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0
//
// Derived from @ory/nextjs (Apache-2.0).

import { NextResponse, type NextRequest } from "next/server";
import { serialize, SerializeOptions } from "cookie";
import { parse, splitCookiesString } from "set-cookie-parser";
import { guessCookieDomain } from "./cookie";
import { rewriteUrls } from "./rewrite";
import type { OryMiddlewareOptions } from "./types";
import { orySdkUrl } from "./url";

export const defaultForwardedHeaders = [
  "accept",
  "accept-charset",
  "accept-encoding",
  "accept-language",
  "authorization",
  "cache-control",
  "content-type",
  "cookie",
  "host",
  "user-agent",
  "referer",
];

export const defaultOmitHeaders = [
  "transfer-encoding",
  "content-encoding",
  "content-length",
];

export function getProjectApiKey() {
  return (process.env.ORY_PROJECT_API_TOKEN ?? "").replace(/\/$/, "");
}

export function filterRequestHeaders(
  headers: Headers,
  forwardAdditionalHeaders?: string[]
): Headers {
  const filteredHeaders = new Headers();

  headers.forEach((value, key) => {
    const isValid =
      defaultForwardedHeaders.includes(key) ||
      (forwardAdditionalHeaders ?? []).includes(key);
    if (isValid) filteredHeaders.set(key, value);
  });

  return filteredHeaders;
}

export function processSetCookieHeaders(
  protocol: string,
  fetchResponse: Response,
  options: OryMiddlewareOptions,
  requestHeaders: Headers
) {
  const isTls =
    protocol === "https:" ||
    requestHeaders.get("x-forwarded-proto") === "https";

  const forwarded = requestHeaders.get("x-forwarded-host");
  const host = forwarded ? forwarded : requestHeaders.get("host");
  const domain =
    host && !options.forceCookieDomain
      ? guessCookieDomain(host ?? "")
      : options.forceCookieDomain;

  return parse(
    splitCookiesString(fetchResponse.headers.get("set-cookie") || "")
  )
    .map((cookie) => ({
      ...cookie,
      domain,
      secure: isTls,
      encode: (v: string) => v,
    }))
    .map(({ value, name, ...options }) =>
      serialize(name, value, options as SerializeOptions)
    );
}

export async function proxyRequest(
  request: NextRequest,
  options: OryMiddlewareOptions
) {
  const match = [
    "/self-service",
    "/sessions/whoami",
    "/ui",
    "/.well-known/ory",
    "/.ory",
  ];
  if (!match.some((m) => request.nextUrl.pathname.startsWith(m))) {
    return NextResponse.next();
  }

  const appBaseHost = request.headers.get("host");

  const matchBaseUrl = new URL(orySdkUrl());
  const selfUrl =
    request.nextUrl.protocol + "//" + (appBaseHost || request.nextUrl.host);

  const upstreamUrl = request.nextUrl.clone();
  upstreamUrl.hostname = matchBaseUrl.hostname;
  upstreamUrl.host = matchBaseUrl.host;
  upstreamUrl.protocol = matchBaseUrl.protocol;
  upstreamUrl.port = matchBaseUrl.port;

  const upstreamRequestHeaders = filterRequestHeaders(
    request.headers,
    options.forwardAdditionalHeaders
  );
  upstreamRequestHeaders.set("Host", upstreamUrl.host);

  // Ensures we use the correct URL in redirects like OIDC redirects.
  upstreamRequestHeaders.set("Ory-Base-URL-Rewrite", selfUrl.toString());
  upstreamRequestHeaders.set("Ory-Base-URL-Rewrite-Token", getProjectApiKey());

  // We disable custom domain redirects.
  upstreamRequestHeaders.set("Ory-No-Custom-Domain-Redirect", "true");

  const upstreamResponse = await fetch(upstreamUrl.toString(), {
    method: request.method,
    headers: upstreamRequestHeaders,
    body:
      request.method !== "GET" && request.method !== "HEAD"
        ? await request.arrayBuffer()
        : null,
    redirect: "manual",
  });

  defaultOmitHeaders.forEach((header) => {
    upstreamResponse.headers.delete(header);
  });

  if (upstreamResponse.headers.get("set-cookie")) {
    const cookies = processSetCookieHeaders(
      request.nextUrl.protocol,
      upstreamResponse,
      options,
      request.headers
    );
    upstreamResponse.headers.delete("set-cookie");
    cookies.forEach((cookie) => {
      upstreamResponse.headers.append("Set-Cookie", cookie);
    });
  }

  const originalLocation = upstreamResponse.headers.get("location");
  if (originalLocation) {
    let location = originalLocation;

    // The legacy hostedui does a redirect to `../self-service` which breaks the NextJS middleware.
    // To fix this, we hard-rewrite `../self-service`.
    //
    // This is not needed with the "new" account experience based on this SDK.
    if (location.startsWith("../self-service")) {
      location = location.replace("../self-service", "/self-service");
    } else if (!location.startsWith("http")) {
      // If the location header is not an absolute URL, we need to make it one for rewriteUrls to properly rewrite it.
      location = new URL(location, matchBaseUrl).toString();
    }

    location = rewriteUrls(location, matchBaseUrl.toString(), selfUrl, options);

    if (!location.startsWith("http")) {
      location = new URL(location, selfUrl).toString();
    }

    // Next.js throws an error that is completely unhelpful if the location header is not an absolute URL.
    // Therefore, we throw a more helpful error message here.
    if (!location.startsWith("http")) {
      throw new Error(
        "The HTTP location header must be an absolute URL in NextJS middlewares. However, it is not. The resulting HTTP location is `" +
          location +
          "`. This is either a configuration or code bug."
      );
    }

    upstreamResponse.headers.set("location", location);
  }

  let modifiedBody = Buffer.from(await upstreamResponse.arrayBuffer());
  if (
    upstreamResponse.headers.get("content-type")?.includes("text/") ||
    upstreamResponse.headers.get("content-type")?.includes("application/json")
  ) {
    const bufferString = modifiedBody.toString("utf-8");
    modifiedBody = Buffer.from(
      rewriteUrls(bufferString, matchBaseUrl.toString(), selfUrl, options)
    );
  }

  return new NextResponse(modifiedBody, {
    headers: upstreamResponse.headers,
    status: upstreamResponse.status,
  });
}

/**
 * Creates a Next.js middleware function that proxies requests to the Ory SDK.
 */
export function createOryMiddleware(options: OryMiddlewareOptions) {
  return (r: NextRequest) => {
    return proxyRequest(r, options);
  };
}

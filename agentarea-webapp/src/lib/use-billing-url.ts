"use client";

import { useEffect, useState } from "react";

/**
 * Where this deployment's billing page lives, or "" when it has none.
 *
 * Read from window.__ENV__ rather than process.env.NEXT_PUBLIC_*: Next.js inlines
 * NEXT_PUBLIC_ values at BUILD time, so one shared image could never be told at runtime
 * where its billing page is -- it would silently render no link. The root layout writes
 * this into __ENV__ from a plain server-side variable.
 *
 * Deliberately resolved in an effect. The value does not exist during server rendering,
 * and reading it straight from window would make the server and client disagree about
 * whether the link is there. One frame without it beats a hydration mismatch.
 */
export function useBillingUrl(): string {
  const [url, setUrl] = useState("");

  useEffect(() => {
    const env = (window as { __ENV__?: { CLIENT_BILLING_URL?: string } }).__ENV__;
    setUrl(env?.CLIENT_BILLING_URL?.trim() ?? "");
  }, []);

  return url;
}

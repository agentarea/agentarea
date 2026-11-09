"use client";

import { useEffect, useState } from "react";

type ClientEnv = { CLIENT_BILLING_URL?: string; CLIENT_SUPPORT_URL?: string };

/**
 * A deployment setting the root layout wrote into window.__ENV__, or "" when unset.
 *
 * Read from window.__ENV__ rather than process.env.NEXT_PUBLIC_*: Next.js inlines
 * NEXT_PUBLIC_ values at BUILD time, so one shared image could never be told at runtime
 * where its billing or support page is -- it would silently render no link.
 *
 * Deliberately resolved in an effect. The value does not exist during server rendering,
 * and reading it straight from window would make the server and client disagree about
 * whether the link is there. One frame without it beats a hydration mismatch.
 */
export function useClientEnv(key: keyof ClientEnv): string {
  const [value, setValue] = useState("");

  useEffect(() => {
    const env = (window as { __ENV__?: ClientEnv }).__ENV__;
    setValue(env?.[key]?.trim() ?? "");
  }, [key]);

  return value;
}

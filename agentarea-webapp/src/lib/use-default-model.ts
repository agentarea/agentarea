"use client";

import { useEffect, useMemo, useState } from "react";
import type { ModelInstanceResponse } from "@/api/client/types.gen";
import { defaultModelId } from "@/lib/default-model";

/**
 * The model a new agent starts on, among `instances`; `undefined` until mounted.
 *
 * DEFAULT_PLATFORM_MODEL comes from window.__ENV__ for the reason given in
 * use-billing-url.ts: one image, configured per deployment at runtime. It is read
 * in an effect because the server render has no window, so the default lands one
 * frame after hydration rather than causing a mismatch.
 */
export function useDefaultModelId(
  instances: Pick<
    ModelInstanceResponse,
    "id" | "model_name" | "is_active" | "managed_by"
  >[]
): string | null | undefined {
  const [preferredName, setPreferredName] = useState<string | undefined>();

  useEffect(() => {
    const env = (window as { __ENV__?: { DEFAULT_PLATFORM_MODEL?: string } })
      .__ENV__;
    setPreferredName(env?.DEFAULT_PLATFORM_MODEL?.trim() ?? "");
  }, []);

  return useMemo(
    () =>
      preferredName === undefined
        ? undefined
        : defaultModelId(instances, preferredName),
    [instances, preferredName]
  );
}

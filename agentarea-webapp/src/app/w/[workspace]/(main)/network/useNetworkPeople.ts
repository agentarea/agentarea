"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type { NetworkPeopleAccessResponse } from "@/api/client/types.gen";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import type { NetworkActionResult } from "./actions";

export type PeopleStatus = "loading" | "ready" | "error" | "adminOnly";

export function useNetworkPeople(
  canAdminister: boolean,
  load?: () => Promise<NetworkActionResult<NetworkPeopleAccessResponse>>,
  scopeKey?: unknown
) {
  const t = useTranslations("NetworkPage.people");
  const [data, setData] = useState<NetworkPeopleAccessResponse | null>(null);
  const [status, setStatus] = useState<PeopleStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!canAdminister) return;
    let cancelled = false;
    setData(null);
    setError(null);
    setStatus("loading");
    if (!load) {
      setStatus("error");
      return;
    }
    void load()
      .then((result) => {
        if (cancelled) return;
        if (result.error || !result.data) {
          setError(apiErrorMessage(result, t("unavailableShort")));
          setStatus("error");
          return;
        }
        setData(result.data);
        setStatus("ready");
      })
      .catch((reason: unknown) => {
        console.error("Failed to load network people access:", reason);
        if (!cancelled) {
          setError(`${t("unavailableShort")}: ${formatApiError(reason)}`);
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [canAdminister, load, attempt, scopeKey, t]);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return {
    data,
    status: canAdminister ? status : ("adminOnly" as const),
    error,
    reload,
  };
}

"use client";

import { useCallback, useEffect, useState } from "react";
import type { NetworkPeopleAccessResponse } from "@/api/client/types.gen";
import type { PeopleStatus } from "./components/NetworkPeopleNode";

export function useNetworkPeople(
  canAdminister: boolean,
  load?: () => Promise<NetworkPeopleAccessResponse>,
  scopeKey?: unknown
) {
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
        if (!cancelled) {
          setData(result);
          setStatus("ready");
        }
      })
      .catch((reason: unknown) => {
        console.error("Failed to load network people access:", reason);
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [canAdminister, load, attempt, scopeKey]);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return {
    data,
    status: canAdminister ? status : ("adminOnly" as const),
    error,
    reload,
  };
}

"use client";

import { useCallback, useEffect, useState } from "react";
import type { NetworkPeopleAccessResponse } from "@/api/client/types.gen";
import type { PeopleStatus } from "./components/NetworkPeopleNode";

export function useNetworkPeople(
  enabled: boolean,
  load?: () => Promise<NetworkPeopleAccessResponse>,
  scopeKey?: unknown
) {
  const [data, setData] = useState<NetworkPeopleAccessResponse | null>(null);
  const [status, setStatus] = useState<PeopleStatus>("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setData(null);
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
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, load, attempt, scopeKey]);
  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { data, status, reload };
}

"use client";

import { useSyncExternalStore } from "react";

const noopSubscribe = () => () => {};

const readClientApiUrl = () =>
  (window as Window & { __ENV__?: { CLIENT_API_URL?: string } }).__ENV__
    ?.CLIENT_API_URL || "";

/**
 * The API's public base URL, as the root layout writes it into window.__ENV__.
 *
 * It does not exist during server rendering, so the server renders "" and the
 * client fills it in right after hydration. Reading window straight in render
 * would make the two disagree and fail hydration.
 */
export function useClientApiUrl(): string {
  return useSyncExternalStore(noopSubscribe, readClientApiUrl, () => "");
}

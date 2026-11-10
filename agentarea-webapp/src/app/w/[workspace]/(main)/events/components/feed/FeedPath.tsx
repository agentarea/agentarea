"use client";

import { createContext, useContext, type ReactNode } from "react";
import {
  feedHref,
  WORKSPACE_FEED,
  type FeedPath,
  type FeedState,
} from "@/lib/eventFeed";

const FeedPathContext = createContext<FeedPath>(WORKSPACE_FEED);

/**
 * The page a feed lives on, for its links: the workspace's by default, a
 * stream's on that stream's page.
 */
export function FeedPathProvider({
  path,
  children,
}: {
  path: FeedPath;
  children: ReactNode;
}) {
  return (
    <FeedPathContext.Provider value={path}>{children}</FeedPathContext.Provider>
  );
}

/** The page this feed lives on. */
export function useFeedPath(): FeedPath {
  return useContext(FeedPathContext);
}

/** `feedHref` on the page this feed lives on. */
export function useFeedHref() {
  const path = useContext(FeedPathContext);
  return (state: FeedState, patch: Partial<FeedState> = {}) =>
    feedHref(state, patch, path);
}

"use client";

import {
  createContext,
  useContext,
  useState,
  useTransition,
  type ReactNode,
} from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";

interface FeedSelectionValue {
  /** The event being opened (or `null`, being closed) until its page arrives. */
  pending: string | null | undefined;
  /** Opens `eventId` (or closes the panel, with `null`) at `href`. */
  select: (href: string, eventId: string | null) => void;
}

const FeedSelectionContext = createContext<FeedSelectionValue | null>(null);

/**
 * The open event lives in the URL; this shows the choice at once, so the row
 * and the side panel react on click instead of after the server answers.
 */
export function FeedSelectionProvider({ children }: { children: ReactNode }) {
  const router = useWorkspaceRouter();
  const [isPending, startTransition] = useTransition();
  const [target, setTarget] = useState<string | null>(null);
  const select = (href: string, eventId: string | null) => {
    setTarget(eventId);
    startTransition(() => router.push(href, { scroll: false }));
  };
  return (
    <FeedSelectionContext.Provider
      value={{ pending: isPending ? target : undefined, select }}
    >
      {children}
    </FeedSelectionContext.Provider>
  );
}

export function useFeedSelection(): FeedSelectionValue {
  const value = useContext(FeedSelectionContext);
  if (!value) throw new Error("useFeedSelection needs a FeedSelectionProvider");
  return value;
}

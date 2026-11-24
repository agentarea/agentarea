"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useTransition,
} from "react";
import type { ReactNode, TransitionStartFunction } from "react";

// ── Shared "type switch in flight" signal ──
// The type tabs live in the ContentBlock subheader while the gallery lives in
// the content area, so the transition that wraps the SSR round-trip is owned
// here and consumed by both: the tabs trigger it, the gallery skeletons its
// content on `isPending` for the whole round-trip. This keeps the persistent
// chrome mounted and — crucially — avoids any flash of the previous type's data
// mid-switch (React holds the old tree during a transition, so a type-vs-seed
// comparison would briefly read stale; `isPending` doesn't).
//
// The kind of switch matters for how the wait is shown. Changing type makes the
// current results wrong, so they're replaced by a skeleton. Changing a filter
// within a type only narrows them, and search round-trips on every debounced
// keystroke — skeletoning there would strobe the whole list while you type — so
// the previous results stay on screen, dimmed, until the new page lands.
type PendingKind = "type" | "filters" | null;

type ExplorePending = {
  isPending: boolean;
  pendingKind: PendingKind;
  startTypeTransition: TransitionStartFunction;
  startFilterTransition: TransitionStartFunction;
  /**
   * Title of the item open in the gallery (?item=), so the page header can
   * read "Catalog › GitHub". The gallery resolves it; the header shows it.
   */
  activeTitle: string | null;
  setActiveTitle: (title: string | null) => void;
};
const ExplorePendingContext = createContext<ExplorePending | null>(null);

export function ExplorePendingProvider({ children }: { children: ReactNode }) {
  const [isPending, startTransition] = useTransition();
  const [pendingKind, setPendingKind] = useState<PendingKind>(null);
  const [activeTitle, setActiveTitle] = useState<string | null>(null);

  const startTypeTransition = useCallback<TransitionStartFunction>(
    (fn) => {
      setPendingKind("type");
      startTransition(fn);
    },
    [startTransition]
  );
  const startFilterTransition = useCallback<TransitionStartFunction>(
    (fn) => {
      setPendingKind("filters");
      startTransition(fn);
    },
    [startTransition]
  );

  const value = useMemo(
    () => ({
      isPending,
      pendingKind,
      startTypeTransition,
      startFilterTransition,
      activeTitle,
      setActiveTitle,
    }),
    [
      isPending,
      pendingKind,
      startTypeTransition,
      startFilterTransition,
      activeTitle,
    ]
  );
  return (
    <ExplorePendingContext.Provider value={value}>
      {children}
    </ExplorePendingContext.Provider>
  );
}

export function useExplorePending() {
  return useContext(ExplorePendingContext);
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { withActive, type TabState } from "./tab-state";

const EMPTY: TabState = { open: [], active: null };

const storageKey = (surface: string) => `agentarea.files.tabs:${surface}`;

function read(surface: string): TabState | null {
  try {
    const raw = localStorage.getItem(storageKey(surface));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed !== "object" ||
      parsed === null ||
      !Array.isArray((parsed as TabState).open)
    ) {
      return null;
    }
    const { open, active } = parsed as TabState;
    if (!open.every((path) => typeof path === "string")) return null;
    return withActive(open, typeof active === "string" ? active : null);
  } catch {
    // A quota error, private-browsing lockout or hand-edited entry costs the
    // restored strip, nothing else.
    return null;
  }
}

/** Remember which files were open on one surface, out of the address bar.
 *
 * A strip of tabs is a working session, not a place: a link is worth one file,
 * and a set of twenty would drag all of them through the URL and push a
 * history entry on every click. `seed` is that one linked file — it opens as a
 * tab on top of whatever was remembered.
 *
 * Kept per surface, so a project's tabs never surface in another project's.
 * Entries outlive the files they name; the browser closes those tabs once it
 * sees the listing, so a stale record heals itself rather than accumulating.
 *
 * Starts empty so the server and the first client render agree, then restores
 * on mount. */
export function useFileTabs(
  surface: string,
  seed?: string | null
): [TabState, (next: TabState) => void] {
  const [tabs, setTabs] = useState<TabState>(EMPTY);

  useEffect(() => {
    const restored = read(surface);
    if (!restored && !seed) return;
    setTabs(withActive(restored?.open ?? [], seed ?? restored?.active ?? null));
  }, [surface, seed]);

  const update = useCallback(
    (next: TabState) => {
      setTabs(next);
      try {
        localStorage.setItem(storageKey(surface), JSON.stringify(next));
      } catch {
        // Losing the restore is not worth failing the interaction over.
      }
    },
    [surface]
  );

  return [tabs, update];
}

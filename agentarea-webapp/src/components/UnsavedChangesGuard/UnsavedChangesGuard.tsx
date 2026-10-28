"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import BaseModal from "@/components/BaseModal/BaseModal";

/** Where a click on this anchor would take the app, or null if it stays put or leaves it. */
function inAppDestination(anchor: HTMLAnchorElement): string | null {
  if (anchor.target && anchor.target !== "_self") return null;
  if (anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.href, window.location.href);
  if (url.origin !== window.location.origin) return null;
  // Only the hash changes: the page, and what is typed on it, stays.
  if (
    url.pathname === window.location.pathname &&
    url.search === window.location.search
  )
    return null;
  return url.pathname + url.search + url.hash;
}

/**
 * Asks before the page is left with edits unsaved: an in-app link opens our
 * dialog, closing or reloading the tab gets the browser's own question.
 * `isDirty` is read at that moment, so it can compare against what was saved.
 */
export default function UnsavedChangesGuard({
  isDirty,
}: {
  isDirty: () => boolean;
}) {
  const t = useTranslations("Common.unsavedChanges");
  const router = useRouter();
  const [destination, setDestination] = useState<string | null>(null);
  // The latest check, so the listeners below are added once.
  const isDirtyRef = useRef(isDirty);
  isDirtyRef.current = isDirty;

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      const href = inAppDestination(anchor);
      if (!href || !isDirtyRef.current()) return;
      // Ahead of next/link's own handler, which skips a prevented click.
      event.preventDefault();
      event.stopPropagation();
      setDestination(href);
    };
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!isDirtyRef.current()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, []);

  return (
    <BaseModal
      type="delete"
      title={t("title")}
      description={t("description")}
      confirmLabel={t("leave")}
      open={destination !== null}
      onOpenChange={(open) => {
        if (!open) setDestination(null);
      }}
      onConfirm={() => {
        if (destination) router.push(destination);
      }}
    />
  );
}

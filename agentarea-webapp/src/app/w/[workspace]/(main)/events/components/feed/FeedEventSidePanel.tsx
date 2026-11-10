"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { InfoPanelShell } from "@/components/InfoPanel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import type { SourceType } from "@/lib/sourceTypes";
import FeedEventPanel from "./FeedEventPanel";
import { useFeedSelection } from "./FeedSelection";
import { FeedEventPanelSkeleton } from "./FeedSkeleton";

const NARROW = "(max-width: 1279px)";
const PANEL_WIDTH = 400;

/**
 * The open event in the app's info panel: docked at the right edge of the
 * page on a wide screen, a sheet over the feed on a narrower one. An event
 * picked a moment ago shows its skeleton until it is read; closing goes back
 * to the feed without the event.
 */
export default function FeedEventSidePanel({
  streams,
  sourceTypes,
  children,
}: {
  streams: { id: string; name: string }[];
  sourceTypes: SourceType[];
  /** The server's panel for the event the URL came with. */
  children: ReactNode;
}) {
  const t = useTranslations("EventsPage.panel");
  const {
    selected: shown,
    detail,
    serverRendered,
    select,
    reload,
  } = useFeedSelection();
  const [narrow, setNarrow] = useState<boolean | null>(null);
  const close = () => select(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (narrow !== false || !shown) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented) return;
      if (
        e.target instanceof HTMLElement &&
        e.target.closest("input, textarea, select, [role=dialog]")
      )
        return;
      select(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [narrow, shown, select]);

  const body = shown && (
    <InfoPanelShell className={narrow ? "border-l-0" : undefined}>
      {detail ? (
        <FeedEventPanel
          eventId={shown}
          event={"event" in detail ? detail.event : null}
          error={"error" in detail ? detail.error : undefined}
          onRetry={reload}
          streams={streams}
          sourceTypes={sourceTypes}
        />
      ) : serverRendered ? (
        children
      ) : (
        <FeedEventPanelSkeleton />
      )}
    </InfoPanelShell>
  );

  if (narrow) {
    if (!shown) return null;
    return (
      <Sheet
        open
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <SheetContent
          aria-describedby={undefined}
          side="right"
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="flex w-full flex-col overflow-hidden p-0 sm:max-w-md"
        >
          <SheetTitle className="sr-only">{t("title")}</SheetTitle>
          {body}
        </SheetContent>
      </Sheet>
    );
  }

  // Docked, the panel opens by growing from the page's right edge and folds
  // back on close, with the spring the sidebar moves by; the feed beside it
  // narrows along. A page opened with an event in its URL shows it at once.
  return (
    <AnimatePresence initial={false}>
      {shown && (
        <motion.aside
          key="event-panel"
          aria-label={t("title")}
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: PANEL_WIDTH, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={
            reduceMotion
              ? { duration: 0 }
              : { type: "spring", stiffness: 260, damping: 30, mass: 1 }
          }
          className={
            narrow === null
              ? "relative hidden shrink-0 overflow-hidden xl:block"
              : "relative shrink-0 overflow-hidden"
          }
        >
          <div className="h-full" style={{ width: PANEL_WIDTH }}>
            {body}
          </div>
          <Button
            size="xs"
            variant="ghost"
            onClick={close}
            aria-label={t("close")}
            title={t("close")}
            className="absolute right-2 top-2 h-6 w-6 p-0 text-muted-foreground"
          >
            <X />
          </Button>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}

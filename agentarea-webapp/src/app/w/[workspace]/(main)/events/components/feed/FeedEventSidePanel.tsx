"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";
import { InfoPanelShell } from "@/components/InfoPanel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useFeedSelection } from "./FeedSelection";
import { FeedEventPanelSkeleton } from "./FeedSkeleton";

const NARROW = "(max-width: 1279px)";

/**
 * The open event in the app's info panel: docked at the right edge of the
 * page on a wide screen, a sheet over the feed on a narrower one. An event
 * picked a moment ago shows its skeleton until its page arrives; closing goes
 * back to the feed without the event.
 */
export default function FeedEventSidePanel({
  event,
  closeHref,
  children,
}: {
  /** The event the server rendered `children` for. */
  event: string | undefined;
  closeHref: string;
  children: ReactNode;
}) {
  const t = useTranslations("EventsPage.panel");
  const { pending, select } = useFeedSelection();
  const [narrow, setNarrow] = useState<boolean | null>(null);
  const shown = pending === undefined ? event : pending;
  const close = () => select(closeHref, null);

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
      select(closeHref, null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [narrow, shown, closeHref, select]);

  if (!shown) return null;
  const body = (
    <InfoPanelShell className={narrow ? "border-l-0" : undefined}>
      {shown === event ? children : <FeedEventPanelSkeleton />}
    </InfoPanelShell>
  );

  if (narrow) {
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

  return (
    <aside
      aria-label={t("title")}
      className={
        narrow === null
          ? "relative hidden w-[400px] shrink-0 xl:block"
          : "relative w-[400px] shrink-0"
      }
    >
      {body}
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
    </aside>
  );
}

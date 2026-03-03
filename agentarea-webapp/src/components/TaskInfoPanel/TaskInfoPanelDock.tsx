"use client";

import { ReactNode, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

interface TaskInfoPanelDockProps {
  panel: ReactNode;
  storageKey?: string; // Kept for API compatibility but unused
  className?: string;
  widthPx?: number;
  collapsedWidthPx?: number;
  defaultOpen?: boolean;
}

export default function TaskInfoPanelDock({
  panel,
  storageKey,
  className,
  widthPx = 360,
  collapsedWidthPx = 16,
  defaultOpen = true,
}: TaskInfoPanelDockProps) {
  const t = useTranslations("TaskInfoPanel");
  const isMobile = useIsMobile();

  const effectiveCollapsedWidthPx = isMobile ? 0 : 0; // On mobile, we want it fully hidden, so width is 0. On desktop, also 0 for collapsed state.

  // No localStorage logic anymore.
  // Mobile -> Closed by default
  // Desktop -> Open by default (defaultOpen prop)
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === "undefined") return defaultOpen;
    // On client: check width immediately
    // If mobile (width < 768), force closed.
    // If desktop, use defaultOpen.
    return window.innerWidth >= 768 && defaultOpen;
  });

  const [currentWidth, setCurrentWidth] = useState(widthPx);

  // Responsive width adjustment
  useEffect(() => {
    const handleResize = () => {
      // Check if tablet size (md breakpoint is 768px, lg is 1024px)
      // We want narrower panel on tablet/small desktop
      if (window.innerWidth >= 768 && window.innerWidth < 1024) {
        setCurrentWidth(260);
      } else {
        setCurrentWidth(widthPx);
      }
    };

    // Initial check
    handleResize();

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [widthPx]);

  const panelTransformClosed = useMemo(() => {
    const delta = Math.max(currentWidth - effectiveCollapsedWidthPx, 0);
    return `translateX(${delta}px)`;
  }, [currentWidth, effectiveCollapsedWidthPx]);

  const label = open ? t("closePanel") : t("openPanel");

  const handleButton = (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setOpen((v) => !v)}
      className={cn(
        "absolute -left-5 z-40",
        isMobile ? "top-[6.75rem]" : "top-3",
        "flex h-9 w-5 items-center justify-center",
        "rounded-none rounded-l-md border border-border bg-background/95 shadow-sm",
        "text-muted-foreground hover:bg-muted/70 hover:text-foreground",
        "supports-[backdrop-filter]:bg-background/80 supports-[backdrop-filter]:backdrop-blur",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      )}
    >
      {open ? (
        <ChevronRight className="h-3.5 w-3.5" />
      ) : (
        <ChevronLeft className="h-3.5 w-3.5" />
      )}
      <span className="sr-only">{label}</span>
    </button>
  );

  return (
    <>
      {isMobile && open && (
        <button
          type="button"
          aria-hidden="true"
          tabIndex={-1}
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-30 bg-black/20"
        />
      )}

      <div
        className={cn(
          "relative h-full flex-shrink-0 overflow-visible",
          isMobile
            ? "transition-transform duration-200 ease-out"
            : "transition-[width] duration-200 ease-out",
          isMobile ? "fixed inset-y-0 right-0 z-40 w-[95%] max-w-[360px]" : "hidden md:block",
          className
        )}
        style={
          isMobile
            ? {
                width: undefined, // Handled by classNames for mobile
                transform: open
                  ? "translateX(0)"
                  : `translateX(calc(100% - ${effectiveCollapsedWidthPx}px))`,
              }
            : { width: open ? currentWidth : effectiveCollapsedWidthPx }
        }
      >
        {handleButton}
        <div
          className="absolute inset-y-0 right-0 transition-transform duration-200 ease-out"
          style={{
            width: isMobile ? "100%" : currentWidth,
            transform: isMobile
              ? "translateX(0)"
              : open
                ? "translateX(0)"
                : panelTransformClosed,
          }}
        >
          {panel}
        </div>
      </div>
    </>
  );
}

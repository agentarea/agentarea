"use client";

import { useSyncExternalStore } from "react";
import { useLocale } from "next-intl";
import {
  formatEventTime,
  utcTitle,
  type EventTimeStyle,
} from "@/lib/eventFeed";

const noChange = () => () => {};
const viewerZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverZone = () => "UTC";

/** The viewer's time zone; UTC on the server, which cannot know it. */
export function useViewerZone(): string {
  return useSyncExternalStore(noChange, viewerZone, serverZone);
}

/** A time in the viewer's zone, its full form and UTC in the tooltip. */
export default function EventTime({
  value,
  style,
  className,
}: {
  value: string;
  style: EventTimeStyle;
  className?: string;
}) {
  const locale = useLocale();
  const zone = useViewerZone();
  return (
    <time
      dateTime={value}
      title={utcTitle(value, locale, zone)}
      className={className}
      suppressHydrationWarning
    >
      {formatEventTime(value, locale, zone, style)}
    </time>
  );
}

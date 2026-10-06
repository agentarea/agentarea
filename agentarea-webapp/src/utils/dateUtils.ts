import { useLocale, useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";

/** Parse server timestamps, treating offsetless ISO date-times as UTC. */
export function parseUtcTimestamp(
  value: string | null | undefined
): Date | null {
  if (!value) return null;
  const offsetlessIsoDateTime =
    /^\d{4}-\d{2}-\d{2}T/i.test(value) &&
    !/(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(value);
  const date = new Date(offsetlessIsoDateTime ? `${value}Z` : value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Calendar date in the active locale ("23 Sept 2026"); "—" when missing. */
export function formatDate(value: string | null | undefined, locale: string) {
  const date = parseUtcTimestamp(value);
  if (!date) return "—";
  return date.toLocaleDateString(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Calendar date + time in the active locale ("23 Sept 2026, 14:05 UTC"); "—"
 * when missing. Pinned to UTC with the zone labelled, not the server's local
 * zone: this runs in server components, so an unlabelled local time would be
 * the server's, not the viewer's (there is no viewer time zone available
 * here to render in instead).
 */
export function formatDateTime(
  value: string | null | undefined,
  locale: string
) {
  const date = parseUtcTimestamp(value);
  if (!date) return "—";
  return date.toLocaleString(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export const getValidTimestamp = (timestamp?: string | null): number | null =>
  parseUtcTimestamp(timestamp)?.getTime() ?? null;

export const formatRelativeTime = (
  timestamp?: string | null,
  fallback = "-"
): string => {
  const time = getValidTimestamp(timestamp);
  if (time === null) {
    return fallback;
  }

  return formatDistanceToNow(new Date(time), { addSuffix: true });
};

// Hook: returns a timestamp formatter bound to the active locale + translations.
// Must be called from a component/hook — it uses next-intl hooks. (Replaces the
// old `formatTimestamp()` which called hooks from a plain function, violating
// the Rules of Hooks.)
export const useFormatTimestamp = (): ((timestamp: string) => string) => {
  const t = useTranslations("Common");
  const locale = useLocale();

  return (timestamp: string): string => {
    const date = parseUtcTimestamp(timestamp);
    if (!date) return "—";
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);

    const isToday = date.toDateString() === today.toDateString();
    const isYesterday = date.toDateString() === yesterday.toDateString();

    const timeString = date.toLocaleTimeString(locale, {
      hour: "2-digit",
      minute: "2-digit",
    });

    if (isToday) {
      return `${t("today")} ${t("at")} ${timeString}`;
    } else if (isYesterday) {
      return `${t("yesterday")} ${t("at")} ${timeString}`;
    }
    return `${date.toLocaleDateString("en-GB")} ${t("at")} ${timeString}`;
  };
};

import { useLocale, useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";

export const getValidTimestamp = (timestamp?: string | null): number | null => {
  if (!timestamp) {
    return null;
  }

  const time = new Date(timestamp).getTime();
  return Number.isFinite(time) ? time : null;
};

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
    const date = new Date(timestamp);
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

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

export const formatTimestamp = (timestamp: string): string => {
  const t = useTranslations("Common");
  const locale = useLocale();
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
  } else {
    return `${date.toLocaleDateString("en-GB")} ${t("at")} ${timeString}`;
  }
};

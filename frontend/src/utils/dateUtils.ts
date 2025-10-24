import { useTranslations } from "next-intl";

export const formatTimestamp = (timestamp: string): string => {
  const t = useTranslations("Common");
  const date = new Date(timestamp);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);

  const isToday = date.toDateString() === today.toDateString();
  const isYesterday = date.toDateString() === yesterday.toDateString();

  const timeString = date.toLocaleTimeString([], {
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

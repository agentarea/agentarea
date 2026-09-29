// Localized compact relative time ("just now", "5m", "3h", "2d") for the
// dashboard lists. The unit strings come from the message catalog so ru/en
// render in the active language.

type Translator = (key: string, values?: Record<string, string | number>) => string;

export function formatRelTime(iso: string | null, t: Translator): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return t("relJustNow");
  if (mins < 60) return t("relMinutes", { count: mins });
  const hours = Math.round(mins / 60);
  if (hours < 24) return t("relHours", { count: hours });
  return t("relDays", { count: Math.round(hours / 24) });
}

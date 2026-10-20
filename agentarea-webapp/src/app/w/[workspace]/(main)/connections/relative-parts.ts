const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ["year", 365 * 24 * 3600],
  ["month", 30 * 24 * 3600],
  ["week", 7 * 24 * 3600],
  ["day", 24 * 3600],
  ["hour", 3600],
  ["minute", 60],
];

/**
 * "2 hours ago" split for a stat cell: the number as the big value, the rest
 * ("hours ago", "часа назад") as its unit, both in the given locale.
 */
export function relativeParts(
  iso: string | null | undefined,
  now: Date,
  locale: string
): { value: string; unit: string } | null {
  if (!iso) return null;
  const seconds = (new Date(iso).getTime() - now.getTime()) / 1000;
  const [unit, size] =
    RELATIVE_UNITS.find(([, size]) => Math.abs(seconds) >= size) ??
    RELATIVE_UNITS[RELATIVE_UNITS.length - 1];
  const parts = new Intl.RelativeTimeFormat(locale, {
    numeric: "always",
  }).formatToParts(Math.round(seconds / size), unit);
  return {
    value: parts
      .filter((part) => part.type !== "literal")
      .map((part) => part.value)
      .join(""),
    unit: parts
      .filter((part) => part.type === "literal")
      .map((part) => part.value)
      .join("")
      .trim(),
  };
}

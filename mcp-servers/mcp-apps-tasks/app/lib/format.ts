export { timeAgo } from "@kit/lib/format";

export const formatDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }) + " UTC";

/** A calendar date ("YYYY-MM-DD") as "Oct 7", with the year only when it is not the reference year. */
export function formatDay(date: string, reference: string): string {
  const sameYear = date.slice(0, 4) === reference.slice(0, 4);
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
    timeZone: "UTC",
  });
}

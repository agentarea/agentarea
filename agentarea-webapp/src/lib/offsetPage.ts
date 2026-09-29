/**
 * Page-number paging over an endpoint that takes limit/offset and returns a
 * bare list. Such a list carries no total, so a page asks for one row more
 * than it shows: that row coming back is what says another page follows.
 */

type SearchParams = Record<string, string | string[] | undefined>;

/** The page a `?page=` value names; 1 when absent, null when it is not a page. */
export function parsePageParam(
  raw: string | string[] | undefined
): number | null {
  if (raw === undefined) return 1;
  if (typeof raw !== "string" || !/^[1-9]\d*$/.test(raw)) return null;
  return Number(raw);
}

export function pageWindow(
  page: number,
  pageSize: number
): { limit: number; offset: number } {
  return { limit: pageSize + 1, offset: (page - 1) * pageSize };
}

export function takePage<T>(
  rows: T[],
  pageSize: number
): { rows: T[]; hasNext: boolean } {
  return { rows: rows.slice(0, pageSize), hasNext: rows.length > pageSize };
}

/** Link to `page` that keeps every other single-valued search parameter. */
export function pageHref(
  path: string,
  searchParams: SearchParams,
  page: number
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (key !== "page" && typeof value === "string" && value) {
      params.set(key, value);
    }
  }
  if (page > 1) params.set("page", String(page));
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

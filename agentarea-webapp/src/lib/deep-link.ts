/**
 * A link from outside the app (the landing) cannot know the visitor's
 * workspace, so it targets an unprefixed path that redirects into the personal
 * one. This is the in-workspace path it lands on: `path`, carrying the link's
 * one query value as `param`. The value travels unchecked; the page it lands
 * on validates it, so a broken link says so instead of opening empty.
 */
export function deepLinkPath(
  path: string,
  param: string,
  value: string | string[] | null | undefined
): string {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw) return path;
  return `${path}?${new URLSearchParams({ [param]: raw })}`;
}

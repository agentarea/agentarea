const PROBE_ORIGIN = "http://same-origin.invalid";

/** Whether a URL is a path on this site, so the browser can load it without
 * contacting a host someone else chose. `//host/x` and `/\host/x` are
 * protocol-relative to a browser and are not paths here. */
export function isSameOriginPath(url: string): boolean {
  if (!url.startsWith("/")) return false;
  try {
    return new URL(url, PROBE_ORIGIN).origin === PROBE_ORIGIN;
  } catch {
    return false;
  }
}

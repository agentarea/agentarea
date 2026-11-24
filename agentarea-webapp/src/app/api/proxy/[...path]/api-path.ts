/**
 * True when `url`, as URL parsing resolves it, stays on the API origin under
 * its `/v1/`. Percent-encoded dot segments ("%2e%2e") resolve like "..", so a
 * check on the raw segments is not enough.
 */
export function isUnderVersionedApi(url: string, apiBaseUrl: string): boolean {
  const base = new URL(apiBaseUrl);
  const target = new URL(url);
  const prefix = `${base.pathname.replace(/\/+$/, "")}/v1/`;
  return target.origin === base.origin && target.pathname.startsWith(prefix);
}

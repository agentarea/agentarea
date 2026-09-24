/**
 * Guards a browser navigation target against a non-http(s) scheme.
 *
 * `authorize_url` fields returned by the OAuth-connect endpoints trace back to
 * a remote server's own metadata (or, for the catalog flow, a stored config).
 * A `javascript:`/`data:` value there is a stored XSS the moment the browser
 * navigates to it (#482). Every `window.location.href = ...` /
 * `window.location.assign(...)` / `window.open(...)` site fed by such a URL
 * must check it here first.
 */
export function isSafeRedirectUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

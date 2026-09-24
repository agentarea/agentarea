/**
 * Baseline Content-Security-Policy for the webapp shell — see issue #483.
 *
 * Kept conservative rather than nonce-based: Next.js only applies a CSP
 * nonce to dynamically rendered pages (a statically generated page gets no
 * nonce at build time — see the "How nonces work in Next.js" note in
 * https://nextjs.org/docs/app/guides/content-security-policy), and this app
 * mixes both without a way to verify every route here. `script-src
 * 'unsafe-inline'` is therefore a known, documented gap: the root layout's
 * one inline script (`window.__ENV__`) and Next's own framework scripts
 * need it. `style-src 'unsafe-inline'` covers component libraries (Radix,
 * shadcn) that position themselves via inline `style` attributes.
 *
 * `object-src`, `base-uri` and `frame-ancestors` need no such trade-off and
 * are locked down unconditionally.
 */

function originOf(url: string | undefined | null): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

export interface CspOrigins {
  /** The public origin the browser calls directly for the backend API, if any. */
  apiOrigin?: string | null;
  /** The public origin Ory Elements calls directly for auth flows, if any. */
  oryOrigin?: string | null;
}

export function buildContentSecurityPolicy(origins: CspOrigins): string {
  const extra = [
    ...new Set(
      [origins.apiOrigin, origins.oryOrigin]
        .map(originOf)
        .filter((origin): origin is string => origin !== null)
    ),
  ];

  const connectSrc = ["'self'", ...extra];
  const formAction = ["'self'", ...extra];

  const directives = [
    `default-src 'self'`,
    `script-src 'self' 'unsafe-inline'`,
    `style-src 'self' 'unsafe-inline'`,
    `img-src 'self' data: blob: https: http:`,
    `font-src 'self' data:`,
    `connect-src ${connectSrc.join(" ")}`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `frame-ancestors 'none'`,
    `form-action ${formAction.join(" ")}`,
  ];

  return directives.join("; ");
}

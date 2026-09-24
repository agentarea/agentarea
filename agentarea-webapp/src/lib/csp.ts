/**
 * Baseline Content-Security-Policy for the webapp shell — see issue #483.
 *
 * Built at request time (see src/proxy.ts), never baked into next.config's
 * headers(): this webapp is configured at RUNTIME (window.__ENV__, one built
 * image for every environment — compose, Helm, RU prod), so any origin in
 * this policy has to come from the environment the request is actually
 * running in, not whatever the build machine happened to have set.
 *
 * Kept conservative rather than nonce-based: Next.js only applies a CSP
 * nonce to dynamically rendered pages (a statically generated page gets no
 * nonce at build time — see the "How nonces work in Next.js" note in
 * https://nextjs.org/docs/app/guides/content-security-policy), and this app
 * mixes both without a way to verify every route here. `script-src
 * 'unsafe-inline'` is therefore a known, documented gap: the root layout's
 * one inline script (`window.__ENV__`) and Next's own framework scripts
 * need it. `style-src 'unsafe-inline'` covers component libraries (Radix,
 * shadcn) that position themselves via inline `style` attributes. Because of
 * `unsafe-inline`, this policy does NOT stop a `javascript:` URL navigation
 * — that needs a nonce or a strict script-src with no `unsafe-inline`. The
 * actual fixes for the stored-XSS in issue #483 are the proxy/backend
 * Content-Disposition + nosniff changes (and #514); this CSP is defense in
 * depth on top of them, not a replacement.
 *
 * `form-action` is intentionally omitted. Chrome enforces `form-action`
 * against the whole post-submit redirect chain, not just the first hop. The
 * Kratos OIDC login is a form POST to Kratos that redirects on to an
 * external IdP (accounts.google.com, github.com, ...), and the Hydra
 * consent "accept" redirects to whatever `redirect_uri` the OAuth client
 * registered — for the Claude/Codex CLI clients, an arbitrary localhost
 * port. Neither destination set can be allowlisted, so shipping
 * `form-action` here would break login.
 *
 * `object-src`, `base-uri` and `frame-ancestors` carry no such trade-off and
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
  ];

  return directives.join("; ");
}

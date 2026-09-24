/**
 * Baseline Content-Security-Policy for the webapp shell — see issue #483.
 * Only directives with no script/origin trade-offs are set; a nonce-based
 * script-src is follow-up work (see the PR description).
 */
export const CONTENT_SECURITY_POLICY =
  "object-src 'none'; base-uri 'self'; frame-ancestors 'none'";

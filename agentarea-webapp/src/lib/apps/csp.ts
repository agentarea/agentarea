import type { McpUiResourceCsp } from "@modelcontextprotocol/ext-apps";

const UNSAFE_DOMAIN_CHARACTERS = /[\s;'"`]/;

function sanitizeDomains(domains: string[] | undefined): string[] {
  return (domains ?? []).filter(
    (domain): domain is string =>
      typeof domain === "string" &&
      domain.length > 0 &&
      !UNSAFE_DOMAIN_CHARACTERS.test(domain)
  );
}

function joinDirective(name: string, sources: string[]): string {
  return [name, ...sources].join(" ");
}

/**
 * Build the HTTP CSP used by the dedicated Apps sandbox origin.
 *
 * Domain declarations are treated as data, not directives: values that could
 * terminate a directive or inject a CSP keyword are omitted.
 */
export function buildSandboxCsp(
  csp: McpUiResourceCsp | undefined,
  appOrigin: string
): string {
  const resources = sanitizeDomains(csp?.resourceDomains);
  const connect = sanitizeDomains(csp?.connectDomains);
  const frames = sanitizeDomains(csp?.frameDomains);
  const baseUris = sanitizeDomains(csp?.baseUriDomains);
  const safeAppOrigin = sanitizeDomains([appOrigin])[0] ?? "'none'";

  return [
    "default-src 'none'",
    // The app already runs arbitrary inline script in its own origin, so eval
    // grants it nothing new; view libraries that compile templates (Cesium's
    // Knockout bindings) need it. The ext-apps reference host allows it too.
    joinDirective("script-src", [
      "'self'",
      "'unsafe-inline'",
      "'unsafe-eval'",
      ...resources,
    ]),
    joinDirective("style-src", ["'self'", "'unsafe-inline'", ...resources]),
    joinDirective("img-src", ["'self'", "data:", ...resources]),
    joinDirective("media-src", ["'self'", "data:", ...resources]),
    joinDirective("font-src", ["'self'", "data:", ...resources]),
    connect.length > 0
      ? joinDirective("connect-src", connect)
      : "connect-src 'none'",
    joinDirective("worker-src", ["'self'", "blob:", ...resources]),
    frames.length > 0 ? joinDirective("frame-src", frames) : "frame-src 'none'",
    baseUris.length > 0
      ? joinDirective("base-uri", baseUris)
      : "base-uri 'self'",
    `frame-ancestors ${safeAppOrigin}`,
  ].join("; ");
}

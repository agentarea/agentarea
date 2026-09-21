import type { EntityKind } from "@/lib/entity-icons";

/**
 * How one entity is depicted: its own logo when the registry gives us one, the
 * domain it points at when it does not, and the kind's glyph as the last
 * honest fallback. Pairs with `@/lib/entity-icons`, which answers the coarser
 * question of what an entity *is*.
 *
 * Resolution here is pure and server-safe. `<EntityMark>` walks `sources` at
 * render time and drops to `initials`, then the glyph, as candidates fail.
 */
export interface EntityIdentity {
  kind: EntityKind;
  /** Logo URLs, tried in order — the first that loads wins. */
  sources: string[];
  /** Two-letter domain mark, shown when no logo loads. */
  initials?: string;
}

/**
 * Last-resort logo for a kind that has a real mark of its own — better than a
 * lucide glyph, which says "some server" rather than "MCP". Appended to every
 * source chain by `<EntityMark>`, so no caller has to remember it.
 */
export const BRAND_MARKS: Partial<Record<EntityKind, string>> = {
  mcp: "/mcp.svg",
};

type JsonSpecLike = { icons?: unknown } | null | undefined;

/**
 * Minimal shape needed to resolve a connection icon: just the `json_spec`.
 * Both the OpenAPI-schema instance and server types (whose `json_spec` is a
 * `Record<string, unknown>`) satisfy this, so callers pass them directly — no
 * `as any`. Kept narrow on purpose so it doesn't drag in `verification`/`tools`.
 */
export type IconSpecSource = { json_spec?: Record<string, unknown> | null };

/** First icon URL declared by a raw registry ServerJSON spec. */
export function firstIconSrc(spec: JsonSpecLike): string | undefined {
  const firstIcon = Array.isArray(spec?.icons) ? spec.icons[0] : undefined;
  if (firstIcon && typeof firstIcon === "object" && "src" in firstIcon) {
    const src = (firstIcon as { src?: unknown }).src;
    return typeof src === "string" && src.length > 0 ? src : undefined;
  }
  return undefined;
}

export function getMCPConnectionIconSrc(
  instance: IconSpecSource,
  serverSpec?: IconSpecSource | null
): string | undefined {
  return firstIconSrc(instance.json_spec) ?? firstIconSrc(serverSpec?.json_spec);
}

/**
 * The hostname with a leading service label removed, when one is there. These
 * three name an endpoint rather than a brand (`api.stripe.com`,
 * `mcp.notion.com`), and the brand is where the logo lives.
 */
function siteHost(hostname: string): string {
  const stripped = hostname.replace(/^(api|www|mcp)\./, "");
  return stripped.split(".").filter(Boolean).length > 1 ? stripped : hostname;
}

/**
 * Favicon candidates for a service we only know by the URL it is reached at:
 * the host itself first, then the site behind an `api.` subdomain.
 *
 * Requested straight from the host by the browser — deliberately not through a
 * third-party icon service, which would hand every customer's API domain to an
 * outside party, and not through `next/image`, which would make *our* server
 * fetch an arbitrary URL. Always https, since an http icon on an https page is
 * blocked as mixed content anyway.
 */
export function faviconSources(url: string | null | undefined): string[] {
  if (!url) return [];

  let hostname: string;
  try {
    hostname = new URL(url).hostname;
  } catch {
    // Callers pass raw config values; a host on its own is a fair guess.
    hostname = url.trim();
  }
  if (!hostname || !hostname.includes(".")) return [];

  const site = siteHost(hostname);
  const hosts = site === hostname ? [hostname] : [hostname, site];
  return hosts.map((host) => `https://${host}/favicon.ico`);
}

/**
 * Identity mark for a service reached by URL: two letters from the registrable
 * domain of that URL. Shown when no logo resolves, so there is still something
 * to tell two connections apart by.
 */
export function domainInitials(
  url: string | null | undefined,
  fallback?: string | null
): string {
  const named = (fallback ?? "").slice(0, 2).toUpperCase();
  if (!url) return named || "API";

  try {
    const hostname = new URL(url).hostname
      .replace(/^api\./, "")
      .replace(/^www\./, "");
    const labels = hostname.split(".").filter(Boolean);
    const domain = labels.length > 1 ? labels[labels.length - 2] : labels[0];
    return domain ? domain.slice(0, 2).toUpperCase() : "API";
  } catch {
    return named || "API";
  }
}

export function getOpenApiConnectionInitials(connection?: {
  base_url: string;
  name: string;
}): string {
  if (!connection) return "API";
  return domainInitials(connection.base_url, connection.name);
}

/** Identity of an MCP connection: registry logo, else the generic MCP mark. */
export function mcpIdentity(
  instance: IconSpecSource,
  serverSpec?: IconSpecSource | null,
  endpointUrl?: string | null
): EntityIdentity {
  const logo = getMCPConnectionIconSrc(instance, serverSpec);
  return {
    kind: "mcp",
    sources: logo ? [logo] : faviconSources(endpointUrl),
  };
}

/** Identity of an OpenAPI connection: the favicon of the API it points at. */
export function openApiIdentity(connection: {
  base_url?: string | null;
  name?: string | null;
}): EntityIdentity {
  return {
    kind: "client",
    sources: faviconSources(connection.base_url),
    initials: domainInitials(connection.base_url, connection.name),
  };
}

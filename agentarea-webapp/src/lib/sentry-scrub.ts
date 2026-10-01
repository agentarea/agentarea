/**
 * Query strings and fragments carry bearer values here (?invitation=,
 * consent_challenge, Ory flow ids), and the SDK records URLs outside the
 * reach of its dataCollection switches, so they are cut before sending.
 */
export function stripQuery(url: string): string {
  const cut = url.search(/[?#]/);
  return cut === -1 ? url : url.slice(0, cut);
}

interface UrlBearingEvent {
  request?: { url?: string; query_string?: unknown };
  contexts?: Record<string, Record<string, unknown> | undefined>;
}

export function scrubEventUrls<T extends UrlBearingEvent>(event: T): T {
  if (event.request) {
    delete event.request.query_string;
    if (typeof event.request.url === "string") {
      event.request.url = stripQuery(event.request.url);
    }
  }
  const nextjs = event.contexts?.nextjs;
  if (nextjs && typeof nextjs.request_path === "string") {
    nextjs.request_path = stripQuery(nextjs.request_path);
  }
  return event;
}

const BREADCRUMB_URL_KEYS = ["url", "from", "to"] as const;

export function scrubBreadcrumbUrls<
  T extends { data?: Record<string, unknown> },
>(breadcrumb: T): T {
  const data = breadcrumb.data;
  if (data) {
    for (const key of BREADCRUMB_URL_KEYS) {
      const value = data[key];
      if (typeof value === "string") data[key] = stripQuery(value);
    }
  }
  return breadcrumb;
}

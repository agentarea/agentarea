export interface RedirectTarget {
  host: string;
  loopback: boolean;
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function parse(url: string | null | undefined): URL | null {
  if (!url) return null;
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

/**
 * Where the authorization code goes once the user allows. The client's name is
 * whatever the client registered itself as; this host is what the user can
 * actually judge.
 */
export function redirectTarget(consentRequest: {
  request_url?: string;
  client?: { redirect_uris?: string[] };
}): RedirectTarget | null {
  const requested = parse(consentRequest.request_url)?.searchParams.get(
    "redirect_uri"
  );
  const registered = consentRequest.client?.redirect_uris ?? [];
  const target = requested
    ? parse(requested)
    : registered.length === 1
      ? parse(registered[0])
      : null;
  if (!target || !target.host) return null;
  return { host: target.host, loopback: LOOPBACK_HOSTS.has(target.hostname) };
}

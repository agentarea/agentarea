export interface RedirectTarget {
  host: string;
  loopback: boolean;
}

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/**
 * The host the authorization code goes to once the user allows. The client's
 * name is whatever the client registered itself as; this host is what the
 * user can actually judge. The API picks the URI (the request's redirect_uri,
 * or the client's only registered one).
 */
export function redirectTarget(redirectUri: string): RedirectTarget | null {
  let target: URL;
  try {
    target = new URL(redirectUri);
  } catch {
    return null;
  }
  if (!target.host) return null;
  return { host: target.host, loopback: LOOPBACK_HOSTS.has(target.hostname) };
}

const API_PREFIX = "/v1/";

/**
 * The `/api/proxy` URL for a download link the backend built. The backend
 * returns some links absolute (`API_BASE_URL/v1/workspaces/{slug}/...`) and
 * some root-relative (`/v1/workspaces/{slug}/...`); both already carry the
 * workspace, so only the API path and query are kept.
 */
export function apiProxyUrl(url: string): string {
  const { pathname, search } = new URL(url, "http://relative.invalid");
  const index = pathname.indexOf(API_PREFIX);
  if (index === -1) {
    throw new Error(`${url} is not an API link`);
  }
  return `/api/proxy${pathname.slice(index)}${search}`;
}

/** True for a root-relative API link, which only resolves through the proxy. */
export function isRelativeApiLink(url: string): boolean {
  return url.startsWith(API_PREFIX);
}

/**
 * Response headers for a non-JSON body proxied from the backend.
 *
 * This proxy runs on the webapp's own origin, so a response the browser
 * would render inline instead of downloading — HTML, XHTML or SVG that an
 * agent or a workspace member wrote — must never be allowed to execute
 * there. Content-Disposition is forwarded from the backend, but active
 * content types are always forced to a bare `attachment` regardless of what
 * the backend sent, and every response carries `X-Content-Type-Options:
 * nosniff`. See issue #483.
 */

/** Content types a browser will execute or render as markup if opened directly. */
export const ACTIVE_CONTENT_TYPES = new Set([
  "text/html",
  "application/xhtml+xml",
  "image/svg+xml",
  "text/xml",
  "application/xml",
]);

export interface ProxyBackendHeaders {
  contentType: string | null;
  contentDisposition: string | null;
  contentLength: string | null;
  etag: string | null;
  cacheControl: string | null;
  lastModified: string | null;
}

export function buildProxyResponseHeaders(
  backend: ProxyBackendHeaders
): Record<string, string> {
  const contentType = backend.contentType || "application/octet-stream";
  const normalizedType = contentType.split(";")[0].trim().toLowerCase();

  const headers: Record<string, string> = {
    "content-type": contentType,
    "x-content-type-options": "nosniff",
  };

  if (ACTIVE_CONTENT_TYPES.has(normalizedType)) {
    headers["content-disposition"] = "attachment";
  } else if (backend.contentDisposition) {
    headers["content-disposition"] = backend.contentDisposition;
  }

  if (backend.contentLength) headers["content-length"] = backend.contentLength;
  if (backend.etag) headers["etag"] = backend.etag;
  if (backend.cacheControl) headers["cache-control"] = backend.cacheControl;
  if (backend.lastModified) headers["last-modified"] = backend.lastModified;

  return headers;
}

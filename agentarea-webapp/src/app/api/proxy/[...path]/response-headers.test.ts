import { describe, expect, it } from "vitest";
import {
  ACTIVE_CONTENT_TYPES,
  buildProxyResponseHeaders,
  type ProxyBackendHeaders,
} from "./response-headers";

const backend = (overrides: Partial<ProxyBackendHeaders> = {}): ProxyBackendHeaders => ({
  contentType: "text/plain",
  contentDisposition: null,
  contentLength: null,
  etag: null,
  cacheControl: null,
  lastModified: null,
  ...overrides,
});

describe("buildProxyResponseHeaders", () => {
  it("always sets nosniff", () => {
    const headers = buildProxyResponseHeaders(backend());

    expect(headers["x-content-type-options"]).toBe("nosniff");
  });

  it("forwards the backend's Content-Disposition for an inert content type", () => {
    const headers = buildProxyResponseHeaders(
      backend({
        contentType: "application/pdf",
        contentDisposition: 'attachment; filename="report.pdf"',
      })
    );

    expect(headers["content-disposition"]).toBe('attachment; filename="report.pdf"');
  });

  it("omits Content-Disposition when the backend did not send one for an inert type", () => {
    const headers = buildProxyResponseHeaders(backend({ contentType: "image/png" }));

    expect(headers["content-disposition"]).toBeUndefined();
  });

  for (const contentType of ACTIVE_CONTENT_TYPES) {
    it(`forces a bare attachment for ${contentType} even if the backend said inline`, () => {
      const headers = buildProxyResponseHeaders(
        backend({ contentType, contentDisposition: "inline" })
      );

      expect(headers["content-disposition"]).toBe("attachment");
    });

    it(`forces attachment for ${contentType} when the backend sent no disposition at all`, () => {
      const headers = buildProxyResponseHeaders(backend({ contentType }));

      expect(headers["content-disposition"]).toBe("attachment");
    });
  }

  it("ignores content-type parameters when deciding whether a type is active", () => {
    const headers = buildProxyResponseHeaders(
      backend({ contentType: "text/html; charset=utf-8", contentDisposition: "inline" })
    );

    expect(headers["content-disposition"]).toBe("attachment");
  });

  it("defaults to application/octet-stream when the backend sends no content type", () => {
    const headers = buildProxyResponseHeaders(backend({ contentType: null }));

    expect(headers["content-type"]).toBe("application/octet-stream");
  });

  it("forwards content-length, etag, cache-control and last-modified when present", () => {
    const headers = buildProxyResponseHeaders(
      backend({
        contentLength: "1024",
        etag: '"abc123"',
        cacheControl: "public, max-age=3600",
        lastModified: "Wed, 24 Sep 2026 00:00:00 GMT",
      })
    );

    expect(headers["content-length"]).toBe("1024");
    expect(headers["etag"]).toBe('"abc123"');
    expect(headers["cache-control"]).toBe("public, max-age=3600");
    expect(headers["last-modified"]).toBe("Wed, 24 Sep 2026 00:00:00 GMT");
  });

  it("omits absent optional headers rather than sending empty values", () => {
    const headers = buildProxyResponseHeaders(backend());

    expect("content-length" in headers).toBe(false);
    expect("etag" in headers).toBe(false);
    expect("cache-control" in headers).toBe(false);
    expect("last-modified" in headers).toBe(false);
  });
});

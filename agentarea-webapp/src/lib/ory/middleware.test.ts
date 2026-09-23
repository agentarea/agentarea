import { NextResponse, type NextRequest } from "next/server";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  filterRequestHeaders,
  processSetCookieHeaders,
  proxyRequest,
} from "./middleware";
import type { OryMiddlewareOptions } from "./types";

const ORY_SDK_URL = "https://playground.projects.oryapis.com";

// nextUrl is a NextURL instance in production; only the fields proxyRequest
// touches are modelled here.
class MockNextURL {
  public pathname;
  public protocol;
  public host;
  public hostname;
  public port;
  public origin;

  constructor(public url: string) {
    const parsed = new URL(url);
    this.pathname = parsed.pathname;
    this.protocol = parsed.protocol;
    this.host = parsed.host;
    this.hostname = parsed.hostname;
    this.port = parsed.port;
    this.origin = parsed.origin;
  }

  clone() {
    return new MockNextURL(this.url);
  }

  toString() {
    const port = this.port ? `:${this.port}` : "";
    return `${this.protocol}//${this.hostname}${port}${this.pathname}`;
  }
}

const createMockRequest = (
  url: string,
  options: Partial<NextRequest> = {}
): NextRequest =>
  ({
    nextUrl: new MockNextURL(url) as unknown as NextRequest["nextUrl"],
    method: options.method || "GET",
    headers: new Headers(options.headers || {}),
    arrayBuffer: vi.fn().mockResolvedValue(new ArrayBuffer(0)),
    ...options,
  }) as NextRequest;

const mockFetch = (responseInit: {
  body?: BodyInit;
  headers?: HeadersInit;
  status?: number;
}) => {
  global.fetch = vi.fn().mockResolvedValue(
    new Response(responseInit.body ?? "", {
      headers: new Headers(responseInit.headers ?? {}),
      status: responseInit.status ?? 200,
    })
  );
};

const createOptions = (): OryMiddlewareOptions => ({
  forwardAdditionalHeaders: ["x-custom-header"],
  project: {
    default_locale: "en",
    default_redirect_url: "/custom-redirect",
    error_ui_url: "/auth/error",
    enabled_locales: ["en"],
    locale_behavior: "force_default",
    name: "AgentArea",
    registration_enabled: true,
    verification_enabled: true,
    recovery_enabled: true,
    registration_ui_url: "/auth/registration",
    verification_ui_url: "/auth/verification",
    recovery_ui_url: "/auth/recovery",
    login_ui_url: "/custom-login",
    settings_ui_url: "/auth/settings",
    translations: [],
  },
});

function createMockLoginRequest(
  path: string = "/self-service/login",
  extraHeaders: HeadersInit = {},
  protocol: string = "http"
) {
  return createMockRequest(`${protocol}://localhost${path}`, {
    headers: new Headers({
      host: "localhost",
      ...extraHeaders,
    }),
  });
}

describe("processSetCookieHeaders", () => {
  it.each([
    {
      name: "respects forwarded headers",
      protocol: "http",
      forwardedProtocol: "https",
      setCookie: [["Set-Cookie", "sessionid=abc123; Path=/; HttpOnly"]],
      expected: ["sessionid=abc123; Domain=ory.sh; Path=/; HttpOnly; Secure"],
    },
    {
      name: "marks cookies secure on a TLS request",
      protocol: "https:",
      setCookie: [["set-cookie", "sessionid=abc123; Path=/; HttpOnly"]],
      expected: ["sessionid=abc123; Domain=ory.sh; Path=/; HttpOnly; Secure"],
    },
    {
      name: "supports insecure",
      protocol: "http",
      setCookie: [["set-cookie", "sessionid=abc123; Path=/; HttpOnly"]],
      expected: ["sessionid=abc123; Domain=ory.sh; Path=/; HttpOnly"],
    },
    {
      name: "supports multiple cookies comma separated",
      protocol: "http",
      setCookie: [
        [
          "set-cookie",
          "sessionid1=abc123; Path=/; HttpOnly, sessionid2=123abc; Path=/abc; HttpOnly",
        ],
      ],
      expected: [
        "sessionid1=abc123; Domain=ory.sh; Path=/; HttpOnly",
        "sessionid2=123abc; Domain=ory.sh; Path=/abc; HttpOnly",
      ],
    },
  ])("$name", ({ protocol, forwardedProtocol, setCookie, expected }) => {
    const requestHeaders = new Headers();
    requestHeaders.set("host", "console.ory.sh");
    if (forwardedProtocol) {
      requestHeaders.set("x-forwarded-proto", forwardedProtocol);
    }

    const fetchResponse = new Response(null, {
      headers: new Headers(setCookie as [string, string][]),
    });

    expect(
      processSetCookieHeaders(protocol, fetchResponse, {}, requestHeaders)
    ).toEqual(expected);
  });
});

describe("filterRequestHeaders", () => {
  it("forwards default headers plus the configured extras", () => {
    const headers = new Headers();
    headers.set("authorization", "Bearer token");
    headers.set("content-type", "application/json");
    headers.set("cookie", "sessionid=abc123");
    headers.set("x-custom-header", "custom-value");
    headers.set("x-ignore-header", "custom-value");

    const result = filterRequestHeaders(headers, ["x-custom-header"]);

    expect(result.get("authorization")).toBe("Bearer token");
    expect(result.get("content-type")).toBe("application/json");
    expect(result.get("x-custom-header")).toBe("custom-value");
    expect(result.has("x-ignore-header")).toBe(false);
  });

  it("drops non-default headers when no extras are configured", () => {
    const headers = new Headers();
    headers.set("authorization", "Bearer token");
    headers.set("x-custom-header", "custom-value");

    const result = filterRequestHeaders(headers);

    expect(result.get("authorization")).toBe("Bearer token");
    expect(result.has("x-custom-header")).toBe(false);
  });
});

describe("proxyRequest", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    process.env.ORY_SDK_URL = ORY_SDK_URL;
  });

  afterAll(() => {
    delete process.env.ORY_SDK_URL;
  });

  it("proxies a request and rescopes the set-cookie header", async () => {
    mockFetch({
      headers: new Headers({
        "set-cookie":
          "session=a; Domain=playground.projects.oryapis.com; Path=/; HttpOnly",
        "content-type": "application/json",
      }),
    });

    const response = await proxyRequest(
      createMockLoginRequest(),
      createOptions()
    );

    expect(response).toBeInstanceOf(NextResponse);
    expect(response?.headers.get("set-cookie")).toEqual(
      "session=a; Domain=localhost; Path=/; HttpOnly"
    );
    expect(response?.headers.get("content-type")).toBe("application/json");
  });

  it("rewrites Ory URLs in the JSON body", async () => {
    mockFetch({
      headers: new Headers({ "content-type": "application/json" }),
      body: JSON.stringify({ action: `${ORY_SDK_URL}/self-service/login` }),
    });

    const response = await proxyRequest(
      createMockLoginRequest(),
      createOptions()
    );

    await expect(response?.text()).resolves.toEqual(
      JSON.stringify({ action: "http://localhost/self-service/login" })
    );
  });

  it("rewrites Ory URLs in an HTML body", async () => {
    mockFetch({
      headers: new Headers({ "content-type": "text/html" }),
      body: `<html><a href='${ORY_SDK_URL}/self-service/logout'>logout</a></html>`,
    });

    const response = await proxyRequest(
      createMockLoginRequest(),
      createOptions()
    );

    await expect(response?.text()).resolves.toEqual(
      "<html><a href='http://localhost/self-service/logout'>logout</a></html>"
    );
  });

  it("rewrites an absolute location header on redirects", async () => {
    mockFetch({
      headers: new Headers({
        location: `${ORY_SDK_URL}/self-service/login`,
      }),
      status: 302,
    });

    const response = await proxyRequest(
      createMockLoginRequest(),
      createOptions()
    );

    expect(response?.headers.get("location")).toBe(
      "http://localhost/self-service/login"
    );
    expect(response?.status).toBe(302);
  });

  it("rewrites a relative location header on redirects", async () => {
    mockFetch({
      headers: new Headers({ location: "/ui/welcome" }),
      status: 302,
    });

    const response = await proxyRequest(
      createMockLoginRequest(),
      createOptions()
    );

    expect(response?.headers.get("location")).toBe(
      "http://localhost/custom-redirect"
    );
    expect(response?.status).toBe(302);
  });

  it.each(["login", "registration", "recovery", "verification", "settings"])(
    "maps the Ory %s page to its configured route",
    async (part) => {
      mockFetch({
        headers: new Headers({ location: `${ORY_SDK_URL}/ui/${part}` }),
        status: 302,
      });

      const response = await proxyRequest(createMockLoginRequest(), {
        project: { [`${part}_ui_url`]: `/custom/${part}` },
      });

      expect(response?.headers.get("location")).toBe(
        `http://localhost/custom/${part}`
      );
    }
  );

  it("bypasses requests that do not match proxy paths", async () => {
    mockFetch({ body: "upstream body" });

    const response = await proxyRequest(
      createMockRequest("http://localhost/non-proxy-path"),
      createOptions()
    );

    await expect(response?.text()).resolves.toEqual("");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("preserves additional forwarded headers", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(`${ORY_SDK_URL}/self-service/login`, { status: 200 })
      );
    global.fetch = fetchMock;

    const response = await proxyRequest(
      createMockLoginRequest(undefined, {
        "x-custom-header": "test-value",
        authorization: "Bearer token",
      }),
      createOptions()
    );

    const fetchArgs = fetchMock.mock.calls[0][1];
    expect(fetchArgs.headers.get("x-custom-header")).toBe("test-value");
    expect(fetchArgs.headers.get("authorization")).toBe("Bearer token");

    await expect(response?.text()).resolves.toEqual(
      "http://localhost/self-service/login"
    );
  });
});

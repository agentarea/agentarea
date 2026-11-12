import { describe, expect, it } from "vitest";
import { redirectTarget } from "./redirect-target";

const authorize = (redirect: string) =>
  `https://auth.example/oauth2/auth?client_id=c&redirect_uri=${encodeURIComponent(redirect)}`;

describe("redirectTarget", () => {
  it("names the host the authorize request sends the code to", () => {
    expect(
      redirectTarget({ request_url: authorize("https://evil.example/cb") })
    ).toEqual({ host: "evil.example", loopback: false });
  });

  it("shows the whole host of a look-alike domain", () => {
    expect(
      redirectTarget({
        request_url: authorize("https://app.agentarea.ru.evil.example/cb"),
      })
    ).toEqual({ host: "app.agentarea.ru.evil.example", loopback: false });
  });

  it("marks a loopback callback with its port", () => {
    expect(
      redirectTarget({ request_url: authorize("http://127.0.0.1:33418/callback") })
    ).toEqual({ host: "127.0.0.1:33418", loopback: true });
    expect(
      redirectTarget({ request_url: authorize("http://localhost:9999/cb") })
    ).toEqual({ host: "localhost:9999", loopback: true });
  });

  it("falls back to the client's only registered redirect", () => {
    expect(
      redirectTarget({
        request_url: "https://auth.example/oauth2/auth?client_id=c",
        client: { redirect_uris: ["https://claude.ai/api/mcp/auth_callback"] },
      })
    ).toEqual({ host: "claude.ai", loopback: false });
  });

  it("knows no target when nothing names one unambiguously", () => {
    expect(redirectTarget({})).toBeNull();
    expect(
      redirectTarget({
        client: { redirect_uris: ["https://a.example/cb", "https://b.example/cb"] },
      })
    ).toBeNull();
    expect(redirectTarget({ request_url: authorize("not a url") })).toBeNull();
  });
});

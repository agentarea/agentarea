import { describe, expect, it } from "vitest";
import { redirectTarget } from "./redirect-target";

describe("redirectTarget", () => {
  it("names the host the code is sent to", () => {
    expect(redirectTarget("https://evil.example/cb")).toEqual({
      host: "evil.example",
      loopback: false,
    });
  });

  it("shows the whole host of a look-alike domain", () => {
    expect(redirectTarget("https://app.agentarea.ai.evil.example/cb")).toEqual({
      host: "app.agentarea.ai.evil.example",
      loopback: false,
    });
  });

  it("marks a loopback callback with its port", () => {
    expect(redirectTarget("http://127.0.0.1:33418/callback")).toEqual({
      host: "127.0.0.1:33418",
      loopback: true,
    });
    expect(redirectTarget("http://localhost:9999/cb")).toEqual({
      host: "localhost:9999",
      loopback: true,
    });
  });

  it("knows no target when the API names none", () => {
    expect(redirectTarget("")).toBeNull();
    expect(redirectTarget("not a url")).toBeNull();
    expect(redirectTarget("mailto:a@b.example")).toBeNull();
  });
});

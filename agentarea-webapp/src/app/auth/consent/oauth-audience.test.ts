import { describe, expect, it } from "vitest";
import { grantedAccessTokenAudience } from "./oauth-audience";

describe("grantedAccessTokenAudience", () => {
  it("grants the audience requested by the authorization client", () => {
    expect(
      grantedAccessTokenAudience(
        ["https://api.agentarea.ru/client-mcp/client-id"],
        ["https://api.agentarea.ru"]
      )
    ).toEqual(["https://api.agentarea.ru/client-mcp/client-id"]);
  });

  it("falls back to the registered audience when Hydra ignores the resource parameter", () => {
    expect(
      grantedAccessTokenAudience([], ["https://api.agentarea.ru"])
    ).toEqual(["https://api.agentarea.ru"]);
  });

  it("does not invent an audience when neither source provides one", () => {
    expect(grantedAccessTokenAudience(undefined, undefined)).toEqual([]);
  });
});

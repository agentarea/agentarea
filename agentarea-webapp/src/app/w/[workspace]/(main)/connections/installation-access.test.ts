import { describe, expect, it } from "vitest";
import {
  bindingChanged,
  bindingRequest,
  initialRepositories,
  installationValue,
  USER_TOKEN,
} from "./installation-access";

const target = { instance_id: "11111111-1111-4111-8111-111111111111" };
const bound = { installation_id: 7, account: "acme", repositories: ["web"] };

describe("bindingRequest", () => {
  it("clears the binding for the user's token", () => {
    expect(bindingRequest(target, USER_TOKEN, ["web"])).toEqual({
      ...target,
      installation_id: null,
    });
  });

  it("sends no repositories for the whole installation", () => {
    expect(bindingRequest(target, "7", [])).toEqual({
      ...target,
      installation_id: 7,
      repositories: null,
    });
    expect(bindingRequest(target, "7", ["web"]).repositories).toEqual(["web"]);
  });
});

describe("initialRepositories", () => {
  it("keeps the saved pick of the same installation that still exists", () => {
    expect(initialRepositories(bound, "7", ["api", "web"])).toEqual(["web"]);
    expect(initialRepositories(bound, "7", ["api"])).toEqual([]);
    expect(initialRepositories(bound, "8", ["web"])).toEqual([]);
    expect(initialRepositories(null, "7", ["web"])).toEqual([]);
  });
});

describe("bindingChanged", () => {
  it("compares installation and repositories, order aside", () => {
    expect(installationValue(null)).toBe(USER_TOKEN);
    expect(bindingChanged(null, USER_TOKEN, [])).toBe(false);
    expect(bindingChanged(null, "7", [])).toBe(true);
    expect(bindingChanged(bound, "7", ["web"])).toBe(false);
    expect(bindingChanged(bound, "7", [])).toBe(true);
    expect(
      bindingChanged({ ...bound, repositories: ["b", "a"] }, "7", ["a", "b"])
    ).toBe(false);
    expect(bindingChanged({ ...bound, repositories: null }, "7", [])).toBe(
      false
    );
  });
});

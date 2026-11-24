import { describe, expect, it } from "vitest";
import {
  fromSenders,
  parseSenderIds,
  sendersReady,
  toSenders,
} from "./senders";

describe("senders", () => {
  it("reads ids typed with commas, spaces or new lines, each once", () => {
    expect(parseSenderIds(" 111, 222\n333  111;")).toEqual([
      "111",
      "222",
      "333",
    ]);
  });

  it("saves a list only when it names numeric ids", () => {
    expect(sendersReady({ allow: "ids", ids: "" })).toBe(false);
    expect(sendersReady({ allow: "ids", ids: "111, @alice" })).toBe(false);
    expect(sendersReady({ allow: "ids", ids: "111" })).toBe(true);
    expect(sendersReady({ allow: "owner", ids: "" })).toBe(true);
  });

  it("sends ids only for a list", () => {
    expect(toSenders({ allow: "owner", ids: "111" })).toEqual({
      allow: "owner",
    });
    expect(toSenders({ allow: "ids", ids: "111 222" })).toEqual({
      allow: "ids",
      ids: ["111", "222"],
    });
  });

  it("shows a source added before the choice as admitting members", () => {
    expect(fromSenders(null)).toEqual({ allow: "members", ids: "" });
    expect(fromSenders({ allow: "ids", ids: ["111", "222"] })).toEqual({
      allow: "ids",
      ids: "111, 222",
    });
  });
});

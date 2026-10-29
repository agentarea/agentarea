import { describe, expect, it } from "vitest";
import { formatLogLine } from "./json-console";

const time = new Date("2026-10-27T12:00:00.000Z");
const parse = (line: string) => JSON.parse(line) as Record<string, unknown>;

describe("formatLogLine", () => {
  it("formats a plain message with its time and level", () => {
    expect(parse(formatLogLine("info", ["y"], time))).toEqual({
      time: "2026-10-27T12:00:00.000Z",
      level: "info",
      msg: "y",
    });
  });

  it("keeps an error and its whole stack on one line", () => {
    const line = formatLogLine("error", [new Error("x")], time);
    expect(line).not.toContain("\n");
    const record = parse(line);
    expect(record.msg).toBe("Error: x");
    expect(record.error).toBe("x");
    expect(record.stack).toMatch(/^Error: x\n {4}at /);
  });

  it("puts the cause chain into the stack", () => {
    const error = new TypeError("fetch failed", {
      cause: new Error("connect ECONNREFUSED"),
    });
    const record = parse(formatLogLine("error", ["load failed", error], time));
    expect(record.msg).toBe("load failed TypeError: fetch failed");
    expect(record.stack).toContain("[cause]: Error: connect ECONNREFUSED");
  });

  it("applies format specifiers, objects inline", () => {
    const record = parse(
      formatLogLine("warn", ["%s took %dms", "GET /", 12, { a: [1] }], time)
    );
    expect(record.msg).toBe("GET / took 12ms { a: [ 1 ] }");
  });

  it("strips terminal colours", () => {
    expect(
      parse(formatLogLine("info", ["\x1b[31m⨯\x1b[39m x"], time)).msg
    ).toBe("⨯ x");
  });
});

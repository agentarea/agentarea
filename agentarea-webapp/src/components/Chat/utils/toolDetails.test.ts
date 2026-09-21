import { describe, expect, it } from "vitest";
import { describeToolCall } from "./describeToolCall";
import {
  hasAvailableToolValue,
  isUnavailableToolValue,
  stripUnavailableToolValues,
} from "./toolDetails";

const omitted = "[omitted from event log: 970 units]";
const omittedShort = "[omitted from event log: 20 units]";

describe("tool event detail presentation", () => {
  it("uses the top-level skill name when the result was omitted", () => {
    expect(
      describeToolCall(
        "activate_skill",
        { name: omitted },
        { skill_name: "web-research", exit_code: 0 }
      )
    ).toEqual({ text: "Activated skill web-research" });
  });

  it("does not present an omitted shell command as code", () => {
    expect(
      describeToolCall("run_shell_command", {
        command: omittedShort,
        timeout: 30,
      })
    ).toEqual({ text: "Run shell command" });
  });

  it("removes exact markers recursively while preserving real text", () => {
    const details = {
      command: omittedShort,
      nested: { stdout: omitted, note: "The event log marker is documented." },
      output: "real output",
    };

    expect(isUnavailableToolValue(omitted)).toBe(true);
    expect(isUnavailableToolValue(`${omitted} but this is real prose`)).toBe(
      false
    );
    expect(stripUnavailableToolValues(details)).toEqual({
      nested: { note: "The event log marker is documented." },
      output: "real output",
    });
    expect(hasAvailableToolValue(details)).toBe(true);
    expect(hasAvailableToolValue({ command: omitted, stdout: omitted })).toBe(
      false
    );
  });

  it("drops containers emptied by markers but keeps genuinely empty values", () => {
    expect(
      stripUnavailableToolValues({
        nested: { stdout: omitted },
        emptyObject: {},
        emptyArray: [],
      })
    ).toEqual({ emptyObject: {}, emptyArray: [] });
  });

  it("keeps null values inside genuine structured output", () => {
    expect(hasAvailableToolValue({ error: null })).toBe(true);
    expect(hasAvailableToolValue([null])).toBe(true);
    expect(
      stripUnavailableToolValues({ output: omitted, error: null })
    ).toEqual({ error: null });
    expect(
      hasAvailableToolValue({ output: omitted, error: null })
    ).toBe(true);
  });

  it("recognizes nested and typed sanitizer markers", () => {
    expect(isUnavailableToolValue("[nested value omitted from event log]")).toBe(
      true
    );
    expect(isUnavailableToolValue("[bytes omitted from event log]")).toBe(true);
    expect(isUnavailableToolValue("[object omitted from event log] in prose")).toBe(
      false
    );
  });
});

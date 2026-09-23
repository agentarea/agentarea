import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Part } from "../contract";
import { ToolPart } from "./ToolPart";

const omitted = "[omitted from event log: 970 units]";

function tool(data: Record<string, unknown>): Part {
  return {
    partId: "tool-1",
    kind: "tool",
    eventType: "tool.result",
    data,
  };
}

describe("ToolPart unavailable event details", () => {
  it("shows skill identity and one neutral notice without an empty output panel", () => {
    const markup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "activate_skill",
          skill_name: "web-research",
          result: omitted,
          success: true,
        })}
      />
    );

    expect(markup).toContain("Activated skill web-research");
    expect(markup).toContain("Full details weren’t saved for this run.");
    expect(markup).not.toContain(omitted);
    expect(markup).not.toContain(">Output<");
    expect(markup).not.toContain(">Error<");
    expect(markup).not.toContain("border-border");
  });

  it("keeps failure metadata when shell command and error were omitted", () => {
    const markup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "run_shell_command",
          arguments: { command: omitted, timeout: 30 },
          error: omitted,
          exit_code: 127,
          duration_ms: 42,
          success: false,
        })}
      />
    );

    expect(markup).toContain("Run shell command");
    expect(markup).toContain("exit 127");
    expect(markup).toContain("42 ms");
    expect(markup).toContain("Failed");
    expect(markup).toContain("Full details weren’t saved for this run.");
    expect(markup).not.toContain(omitted);
    expect(markup).not.toContain(">Output<");
    expect(markup).not.toContain(">Error<");
  });

  it("warns when only part of the arguments was omitted", () => {
    const markup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "run_shell_command",
          arguments: { command: omitted, timeout: 30 },
          success: true,
        })}
      />
    );

    expect(markup).toContain("Full details weren’t saved for this run.");
    expect(markup).toContain("&quot;timeout&quot;: 30");
    expect(markup).not.toContain(omitted);
  });

  it("shows numeric execution time in seconds when supplied", () => {
    const markup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "read_file",
          execution_time: 1.25,
          success: true,
        })}
      />
    );

    expect(markup).toContain("1.25 s");
  });

  it("preserves genuine output and error text", () => {
    const outputMarkup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "read_file",
          result: "real output",
          success: true,
        })}
      />
    );
    const errorMarkup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "run_shell_command",
          error: "real error",
          success: false,
          exit_code: 1,
        })}
      />
    );

    // Output and error share one details panel now and are told apart by
    // styling, so there is no section heading left to assert on -- what matters
    // is that neither is dropped on the way in.
    expect(outputMarkup).toContain(">Tool details<");
    expect(outputMarkup).toContain("real output");
    expect(errorMarkup).toContain("real error");
  });

  it("renders structured output containing null instead of dropping it", () => {
    const markup = renderToStaticMarkup(
      <ToolPart
        part={tool({
          tool_name: "read_file",
          result: { error: null },
          success: true,
        })}
      />
    );

    expect(markup).toContain(">Tool details<");
    expect(markup).toContain("&quot;error&quot;: null");
  });
});

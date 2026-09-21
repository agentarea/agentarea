import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TOOL_DETAILS_UNAVAILABLE } from "@/components/Chat/utils/toolDetails";
import type { Part } from "@/lib/events/contract";
import ActivityGroup from "./ActivityGroup";

const omitted = "[omitted from event log: 20 units]";

describe("ActivityGroup unavailable details", () => {
  it("aggregates omitted tool details once for a grouped run", () => {
    const parts: Part[] = Array.from({ length: 5 }, (_, index) => ({
      partId: `tool-${index}`,
      kind: "tool",
      eventType: "tool.result",
      data: {
        tool_name: "run_shell_command",
        result: omitted,
        success: true,
      },
    }));
    const markup = renderToStaticMarkup(
      <ActivityGroup
        run={{
          id: "run-1",
          parts,
          completed: true,
          terminalType: "task.completed",
          actionCount: 5,
          errorCount: 0,
        }}
      />
    );

    expect(markup.split(TOOL_DETAILS_UNAVAILABLE).length - 1).toBe(1);
    expect(markup).not.toContain(omitted);
  });
});

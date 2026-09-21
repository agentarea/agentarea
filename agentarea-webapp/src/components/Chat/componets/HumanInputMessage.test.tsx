import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import HumanInputMessage from "./HumanInputMessage";

describe("HumanInputMessage accessibility", () => {
  it("associates text-like field labels with their controls", () => {
    const markup = renderToStaticMarkup(
      <HumanInputMessage
        data={{
          id: "message-1",
          timestamp: "",
          agent_id: "agent-1",
          event_type: "input.request",
          input_request_id: "request-1",
          question: "Configure review",
          questions: [
            { id: "title", question: "Review title", type: "text" },
            { id: "notes", question: "Success criteria", type: "textarea" },
            { id: "budget", question: "Time budget", type: "number" },
            { id: "token", question: "API token", type: "secret" },
          ],
        }}
      />
    );

    const labelledControlIds = Array.from(
      markup.matchAll(/<label[^>]+for="([^"]+)"/g),
      (match) => match[1]
    );

    expect(labelledControlIds).toHaveLength(4);
    for (const id of labelledControlIds) {
      expect(markup).toMatch(new RegExp(`<(?:input|textarea)[^>]+id="${id}"`));
    }
  });
});

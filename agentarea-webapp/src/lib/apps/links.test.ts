import { describe, expect, it } from "vitest";
import { parseMcpAppLink } from "./links";

describe("parseMcpAppLink", () => {
  it("reads the tool and its string parameters", () => {
    expect(
      parseMcpAppLink(
        "agentarea-app://show_lead_card?contact_id=ct_093&days=30"
      )
    ).toEqual({
      toolName: "show_lead_card",
      params: { contact_id: "ct_093", days: "30" },
    });
  });

  it("keeps the tool name exactly as written", () => {
    expect(parseMcpAppLink("agentarea-app://Show_Lead.Card")?.toolName).toBe(
      "Show_Lead.Card"
    );
    expect(parseMcpAppLink("agentarea-app:show_lead_card")?.toolName).toBe(
      "show_lead_card"
    );
  });

  it("is not an app link for other schemes, missing tools or extra path", () => {
    expect(parseMcpAppLink("https://example.com/show_lead_card")).toBeNull();
    expect(parseMcpAppLink("agentarea-app://")).toBeNull();
    expect(parseMcpAppLink("agentarea-app://show_lead_card/extra")).toBeNull();
    expect(parseMcpAppLink("not a url")).toBeNull();
  });
});

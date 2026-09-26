import { describe, expect, it } from "vitest";
import { buildWorkplaceSuggestions } from "./workplaceSuggestions";

const telegram = {
  id: "telegram",
  name: "Telegram",
  iconUrl: "https://cdn.test/telegram.svg",
};
const slack = { id: "slack", name: "Slack", iconUrl: "https://cdn.test/slack.svg" };

const bare = {
  connectedChannels: [],
  availableChannels: [telegram, slack],
  mcpCount: 0,
  skillCount: 0,
  agentNames: [],
};

describe("what an empty workplace offers", () => {
  it("points a bare workspace at setup, not at made-up tasks", () => {
    const suggestions = buildWorkplaceSuggestions(bare);
    expect(suggestions.every((s) => s.href)).toBe(true);
    expect(suggestions.map((s) => s.href)).toEqual([
      "/triggers/create",
      "/triggers/create",
      "/connections",
      "/skills",
    ]);
  });

  it("shows each channel with the logo the catalog resolved", () => {
    const [first, second] = buildWorkplaceSuggestions(bare);
    expect(first.label).toBe("Put an agent on Telegram");
    expect(first.iconUrl).toBe("https://cdn.test/telegram.svg");
    expect(second.label).toBe("Put an agent on Slack");
    expect(second.iconUrl).toBe("https://cdn.test/slack.svg");
  });

  it("never advertises a channel this deployment does not ship", () => {
    const suggestions = buildWorkplaceSuggestions({
      ...bare,
      availableChannels: [],
    });
    expect(suggestions.some((s) => s.label.includes("Put an agent on"))).toBe(
      false
    );
  });

  it("stops offering to set up what is already there", () => {
    const suggestions = buildWorkplaceSuggestions({
      connectedChannels: [telegram],
      availableChannels: [slack],
      mcpCount: 2,
      skillCount: 1,
      agentNames: ["Triage"],
    });
    expect(suggestions.some((s) => s.href)).toBe(false);
  });

  it("grounds its prompts in the channels that actually exist, logo and all", () => {
    const suggestions = buildWorkplaceSuggestions({
      ...bare,
      connectedChannels: [telegram, slack],
      mcpCount: 1,
      skillCount: 1,
    });
    const catchUp = suggestions.find((s) => s.label === "Catch up on Telegram");
    expect(catchUp?.iconUrl).toBe("https://cdn.test/telegram.svg");
    expect(suggestions.map((s) => s.label)).toContain("Catch up on Slack");
  });

  it("names a real agent rather than a placeholder one", () => {
    const suggestions = buildWorkplaceSuggestions({
      ...bare,
      connectedChannels: [telegram],
      mcpCount: 1,
      skillCount: 1,
      agentNames: ["Inbox triage", "Unused"],
    });
    const agentChip = suggestions.find((s) => s.label.startsWith("Ask "));
    expect(agentChip?.label).toBe("Ask Inbox triage");
    expect(agentChip?.text).toContain("Inbox triage,");
  });

  it("never returns more than it was asked for", () => {
    expect(buildWorkplaceSuggestions(bare, 4)).toHaveLength(4);
  });

  it("leads with setup even once some of the workspace is filled in", () => {
    const suggestions = buildWorkplaceSuggestions({
      ...bare,
      mcpCount: 1,
      skillCount: 1,
    });
    expect(suggestions[0]?.href).toBe("/triggers/create");
    expect(suggestions.at(-1)?.href).toBeUndefined();
  });
});

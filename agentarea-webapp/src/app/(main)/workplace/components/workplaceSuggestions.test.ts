import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import messages from "../../../../../messages/en.json";
import {
  buildWorkplaceSuggestions,
  type WorkspaceShape,
} from "./workplaceSuggestions";

const t = createTranslator({
  locale: "en",
  messages,
  namespace: "Workplace.suggestions",
});
const build = (shape: WorkspaceShape, max?: number) =>
  buildWorkplaceSuggestions(shape, (key, values) => t(key, values), max);

const telegram = {
  id: "telegram",
  name: "Telegram",
  iconUrl: "https://cdn.test/telegram.svg",
};
const slack = {
  id: "slack",
  name: "Slack",
  iconUrl: "https://cdn.test/slack.svg",
  description: "Receive Slack messages and events",
};

const bare = {
  connectedChannels: [],
  availableChannels: [telegram, slack],
  mcpCount: 0,
  skillCount: 0,
  agents: [],
};

describe("what an empty workplace offers", () => {
  it("points a bare workspace at setup, not at made-up tasks", () => {
    const suggestions = build(bare);
    expect(suggestions.every((s) => s.href)).toBe(true);
    expect(suggestions.map((s) => s.href)).toEqual([
      "/triggers/create",
      "/triggers/create",
      "/connections",
      "/skills",
    ]);
  });

  it("shows each channel with the logo the catalog resolved", () => {
    const [first, second] = build(bare);
    expect(first.label).toBe("Put agent on Telegram");
    expect(first.iconUrl).toBe("https://cdn.test/telegram.svg");
    expect(second.label).toBe("Put agent on Slack");
    expect(second.iconUrl).toBe("https://cdn.test/slack.svg");
  });

  it("describes a channel in the catalog's words, or a generic line", () => {
    const [first, second] = build(bare);
    expect(first.hint).toBe("Answer where people already write");
    expect(second.hint).toBe("Receive Slack messages and events");
  });

  it("links setup rows away and fills the composer only for prompts", () => {
    const suggestions = build({
      ...bare,
      connectedChannels: [telegram],
      agents: [{ id: "a1", name: "Triage" }],
    });
    for (const s of suggestions) {
      expect(Boolean(s.href) !== Boolean(s.text)).toBe(true);
    }
  });

  it("never advertises a channel this deployment does not ship", () => {
    const suggestions = build({
      ...bare,
      availableChannels: [],
    });
    expect(suggestions.some((s) => s.label.includes("Put agent on"))).toBe(
      false
    );
  });

  it("stops offering to set up what is already there", () => {
    const suggestions = build({
      connectedChannels: [telegram],
      availableChannels: [slack],
      mcpCount: 2,
      skillCount: 1,
      agents: [{ id: "a1", name: "Triage" }],
    });
    expect(suggestions.some((s) => s.href)).toBe(false);
  });

  it("grounds its prompts in the channels that actually exist, logo and all", () => {
    const suggestions = build({
      ...bare,
      connectedChannels: [telegram, slack],
      mcpCount: 1,
      skillCount: 1,
    });
    const catchUp = suggestions.find((s) => s.label === "Catch up on Telegram");
    expect(catchUp?.iconUrl).toBe("https://cdn.test/telegram.svg");
    expect(suggestions.map((s) => s.label)).toContain("Catch up on Slack");
  });

  it("addresses a real agent with an @ mention, not just its name", () => {
    const suggestions = build({
      ...bare,
      connectedChannels: [telegram],
      mcpCount: 1,
      skillCount: 1,
      agents: [
        { id: "a1", name: "Inbox triage" },
        { id: "a2", name: "Unused" },
      ],
    });
    const agentChip = suggestions.find((s) => s.label.startsWith("Ask "));
    expect(agentChip?.label).toBe("Ask Inbox triage");
    expect(agentChip?.text?.startsWith("@[a1:Inbox triage] ")).toBe(true);
  });

  it("never returns more than it was asked for", () => {
    expect(build(bare, 4)).toHaveLength(4);
  });

  it("leads with setup even once some of the workspace is filled in", () => {
    const suggestions = build({
      ...bare,
      mcpCount: 1,
      skillCount: 1,
    });
    expect(suggestions[0]?.href).toBe("/triggers/create");
    expect(suggestions.at(-1)?.href).toBeUndefined();
  });
});

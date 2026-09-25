import { describe, expect, it } from "vitest";
import { skillDisplay } from "./skill-display";

describe("how a skill reads in a list", () => {
  it("splits an imported name into the skill, its repo and a short hash", () => {
    expect(
      skillDisplay({
        name: "action-creator--anthropics-claude-agent-sdk-demos--73c177cd12",
        source_url:
          "https://github.com/anthropics/claude-agent-sdk-demos/blob/main/email-agent/agent/.claude/skills/action-creator/SKILL.md",
      })
    ).toEqual({
      title: "Action creator",
      subtitle: "anthropics/claude-agent-sdk-demos",
      ref: "73c177",
    });
  });

  it("keeps a name without a hash whole", () => {
    expect(
      skillDisplay({
        name: "agent-browser-vercel-labs-agent-browser",
        source_url:
          "https://github.com/vercel-labs/agent-browser/blob/main/skills/agent-browser/SKILL.md",
      })
    ).toEqual({
      title: "Agent browser vercel labs agent browser",
      subtitle: "vercel-labs/agent-browser",
      ref: null,
    });
  });

  it("falls back to the description when the skill has no repo", () => {
    expect(
      skillDisplay({
        name: "Weekly report",
        description: "Summarise the week for the team",
        source_url: null,
      })
    ).toEqual({
      title: "Weekly report",
      subtitle: "Summarise the week for the team",
      ref: null,
    });
  });

  it("does not mistake a word after -- for a hash", () => {
    expect(skillDisplay({ name: "a--b--notahash" }).ref).toBeNull();
  });
});

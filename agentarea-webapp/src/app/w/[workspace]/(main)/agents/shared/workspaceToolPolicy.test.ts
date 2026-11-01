import { describe, expect, it } from "vitest";
import { workspaceToolVerdicts } from "./workspaceToolPolicy";

describe("workspaceToolVerdicts", () => {
  it("keeps only the tools the workspace denies or holds for approval", () => {
    const verdicts = workspaceToolVerdicts({
      instances: [
        {
          instance_id: "github",
          tools: [
            {
              name: "delete_repo",
              default: "deny",
              effective: "deny",
              reason: null,
            },
            {
              name: "create_issue",
              default: "allow",
              effective: "approval",
              reason: "tool 'create_issue' requires approval",
            },
            {
              name: "list_issues",
              default: "allow",
              effective: "allow",
              reason: null,
            },
          ],
        },
        {
          instance_id: "wiki",
          tools: [
            {
              name: "read",
              default: "allow",
              effective: "allow",
              reason: null,
            },
          ],
        },
      ],
    });

    expect(verdicts).toEqual({
      github: {
        delete_repo: { effective: "deny", reason: null },
        create_issue: {
          effective: "approval",
          reason: "tool 'create_issue' requires approval",
        },
      },
    });
  });
});

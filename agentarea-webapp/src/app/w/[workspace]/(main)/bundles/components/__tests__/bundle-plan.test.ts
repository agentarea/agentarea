import { describe, expect, it } from "vitest";
import type { ImportPreview } from "@/api/client/types.gen";
import {
  analyzeRequestFor,
  buildInstallRequest,
  bundleEditReducer,
  bundlePolicyAsPolicy,
  existingInstall,
  initialEdit,
  installRequestFor,
  isPlanChanged,
  openIssues,
  planKey,
  setupFieldPlacement,
} from "../bundle-plan";

const PLATFORM_DEFAULT = "11111111-1111-4111-8111-111111111111";
const WORKSPACE_MODEL = "22222222-2222-4222-8222-222222222222";

const models = [
  {
    id: PLATFORM_DEFAULT,
    model_name: "luna-6",
    is_active: true,
    managed_by: "platform",
    tags: ["default"],
  },
  {
    id: WORKSPACE_MODEL,
    model_name: "own-key-model",
    is_active: true,
    managed_by: null,
    tags: [],
  },
];

function preview(over: Partial<ImportPreview["bundle"]> = {}): ImportPreview {
  return {
    installable: true,
    setup: [
      {
        key: "model",
        label: "Model",
        type: "string",
        default: WORKSPACE_MODEL,
      },
      {
        key: "gh_token",
        label: "GitHub token",
        type: "secret",
        required: true,
      },
      { key: "region", label: "Region", type: "string" },
    ],
    issues: [
      {
        severity: "block",
        message: "agent 'writer' has no model",
        entity_key: "writer",
      },
      { severity: "warn", message: "something else", entity_key: "writer" },
    ],
    bundle: {
      name: "Research kit",
      agents: [
        {
          key: "researcher",
          name: "Researcher",
          model: "${setup.model}",
          mcps: ["github", "notion"],
        },
        { key: "writer", name: "Writer", model: "gpt-4o", mcps: ["notion"] },
      ],
      mcps: [
        {
          key: "github",
          name: "GitHub",
          json_spec: {},
          bindings: { Authorization: "${setup.gh_token}" },
        },
        { key: "notion", name: "Notion", json_spec: {} },
      ],
      automations: [
        { key: "daily", agent: "writer", cron: "0 9 * * *", prompt: "digest" },
      ],
      policies: [
        {
          key: "no-delete",
          subject: "researcher",
          target: "tool:delete_*",
          effect: "deny",
        },
      ],
      ...over,
    } as ImportPreview["bundle"],
  };
}

describe("agent models", () => {
  const edit = initialEdit(preview(), models);

  it("keeps a model the bundle names when it is a model of this workspace", () => {
    expect(edit.agentModels.researcher).toBe(WORKSPACE_MODEL);
  });

  it("starts an agent whose model is foreign to the workspace on the platform default", () => {
    expect(edit.agentModels.writer).toBe(PLATFORM_DEFAULT);
  });

  it("leaves the pick empty when the workspace has no default to fall back to", () => {
    const own = models.filter((m) => m.id !== PLATFORM_DEFAULT);
    expect(initialEdit(preview(), own).agentModels.writer).toBeNull();
  });
});

describe("install request", () => {
  it("sends the picked model on every agent, foreign literals included", () => {
    let edit = initialEdit(preview(), models);
    edit = bundleEditReducer(edit, {
      type: "setAgentModel",
      key: "researcher",
      modelId: PLATFORM_DEFAULT,
    });
    const { bundle } = buildInstallRequest(preview(), edit, true);
    expect(bundle.agents?.map((a) => [a.key, a.model])).toEqual([
      ["researcher", PLATFORM_DEFAULT],
      ["writer", PLATFORM_DEFAULT],
    ]);
  });

  it("drops an excluded agent with its automations and the connections only it used", () => {
    let edit = initialEdit(preview(), models);
    edit = bundleEditReducer(edit, {
      type: "toggleAgent",
      key: "writer",
      on: false,
    });
    edit = bundleEditReducer(edit, {
      type: "toggleAgentMcp",
      agentKey: "researcher",
      mcpKey: "notion",
      on: false,
    });
    const { bundle } = buildInstallRequest(preview(), edit, true);
    expect(bundle.agents?.map((a) => a.key)).toEqual(["researcher"]);
    expect(bundle.agents?.[0].mcps).toEqual(["github"]);
    expect(bundle.mcps?.map((m) => m.key)).toEqual(["github"]);
    expect(bundle.automations).toEqual([]);
  });

  it("keeps a schedule that runs a saved task while the task's agent stays", () => {
    const withTask = preview({
      tasks: [{ key: "report", name: "Report", agent: "writer", prompt: "go" }],
      automations: [
        { key: "weekly", task: "report", cron: "0 9 * * 1" },
        { key: "legacy", task: "Saved elsewhere", cron: "0 9 * * 1" },
      ],
    });
    const kept = buildInstallRequest(
      withTask,
      initialEdit(withTask, models),
      true
    );
    expect(kept.bundle.automations?.map((a) => a.key)).toEqual([
      "weekly",
      "legacy",
    ]);
    const edit = bundleEditReducer(initialEdit(withTask, models), {
      type: "toggleAgent",
      key: "writer",
      on: false,
    });
    expect(
      buildInstallRequest(withTask, edit, true).bundle.automations?.map(
        (a) => a.key
      )
    ).toEqual(["legacy"]);
  });

  it("sends policies only when the viewer may install them", () => {
    const edit = initialEdit(preview(), models);
    expect(buildInstallRequest(preview(), edit, false).bundle.policies).toEqual(
      []
    );
    expect(
      buildInstallRequest(preview(), edit, true).bundle.policies?.map((p) => [
        p.key,
        p.enabled,
      ])
    ).toEqual([["no-delete", true]]);
  });

  it("drops a policy whose agent is left out, keeps workspace-wide ones", () => {
    const p = preview({
      policies: [
        {
          key: "no-delete",
          subject: "researcher",
          target: "tool:delete_*",
          effect: "deny",
        },
        {
          key: "budget",
          subject: "workspace",
          target: "spend",
          effect: "deny",
        },
      ],
    });
    const edit = bundleEditReducer(initialEdit(p, models), {
      type: "toggleAgent",
      key: "researcher",
      on: false,
    });
    expect(
      buildInstallRequest(p, edit, true).bundle.policies?.map((x) => x.key)
    ).toEqual(["budget"]);
  });

  it("fills a model setup field the picker owns", () => {
    const p = preview();
    p.setup = [
      { key: "model", label: "Model", type: "string", required: true },
    ];
    const { setup_values } = buildInstallRequest(
      p,
      initialEdit(p, models),
      true
    );
    expect(setup_values?.model).toBe(PLATFORM_DEFAULT);
  });
});

describe("analyzer findings", () => {
  it("drops 'has no model' once the agent has a picked model, and nothing else", () => {
    const edit = initialEdit(preview(), models);
    expect(openIssues(preview(), edit).map((i) => i.message)).toEqual([
      "something else",
    ]);
  });

  it("keeps it while the agent has no model to run on", () => {
    const edit = initialEdit(
      preview(),
      models.filter((m) => m.id !== PLATFORM_DEFAULT)
    );
    expect(openIssues(preview(), edit)).toHaveLength(2);
  });
});

describe("setup field placement", () => {
  it("puts a secret beside the connection that binds it and leaves model fields to the agents", () => {
    const p = preview();
    const { byOwner, unbound } = setupFieldPlacement(
      p.setup ?? [],
      p.bundle.mcps ?? [],
      p.bundle.channels ?? [],
      p.bundle.agents ?? []
    );
    expect(byOwner.github?.map((f) => f.key)).toEqual(["gh_token"]);
    expect(unbound.map((f) => f.key)).toEqual(["region"]);
  });
});

describe("bundle policies", () => {
  it("reads an agent-scoped rule as an agent subject", () => {
    expect(
      bundlePolicyAsPolicy(
        {
          key: "no-delete",
          subject: "researcher",
          target: "tool:delete_*",
          effect: "deny",
        },
        true
      )
    ).toMatchObject({
      subject_type: "agent",
      subject_id: "researcher",
      effect: "deny",
    });
  });
});

describe("planKey", () => {
  it("names the same draft the same however its objects were built", () => {
    const a = planKey({ bundle: { name: "b" }, setup_values: { x: 1, y: 2 } });
    const b = planKey({ bundle: { name: "b" }, setup_values: { y: 2, x: 1 } });
    expect(a).toBe(b);
  });

  it("names a draft with another setup value or edit differently", () => {
    const base = planKey({ bundle: { name: "b" }, setup_values: { x: 1 } });
    expect(planKey({ bundle: { name: "b" }, setup_values: { x: 2 } })).not.toBe(
      base
    );
    expect(
      planKey({
        bundle: { name: "b", description: "d" },
        setup_values: { x: 1 },
      })
    ).not.toBe(base);
  });
});

describe("isPlanChanged", () => {
  it("is the 409 install answers for a plan other than the one sent", () => {
    expect(
      isPlanChanged({ status: 409, error: { code: "bundle_plan_changed" } })
    ).toBe(true);
    expect(
      isPlanChanged({
        status: 409,
        error: { code: "approval_enforced_by_policy" },
      })
    ).toBe(false);
    expect(
      isPlanChanged({ status: 400, error: { code: "bundle_install_failed" } })
    ).toBe(false);
  });
});

describe("deploying into an existing install", () => {
  const existing = {
    id: "inst-1",
    name: "Research kit",
    created_by: "u-1",
    updated_by: "u-2",
    updated_at: "2026-11-22T10:00:00Z",
  };
  const taken: ImportPreview = {
    ...preview(),
    installable: false,
    plan_digest: null,
    issues: [
      {
        severity: "block",
        message: "bundle 'Research kit' is already installed",
        code: "bundle_exists",
      },
    ],
    existing_install: existing,
  };

  it("offers the install that has the bundle's name until the user picks it", () => {
    const edit = initialEdit(taken, models);
    expect(existingInstall(taken, edit)).toEqual(existing);
    expect(openIssues(taken, edit)).toHaveLength(1);
    const into = bundleEditReducer(edit, { type: "deployInto", id: "inst-1" });
    expect(existingInstall(taken, into)).toBeNull();
    expect(openIssues(taken, into)).toEqual([]);
  });

  it("does not offer an install for a block it cannot settle", () => {
    const gone: ImportPreview = {
      ...taken,
      existing_install: null,
      issues: [
        {
          severity: "block",
          message: "bundle install x not found",
          code: "bundle_install_not_found",
        },
      ],
    };
    const edit = initialEdit(gone, models);
    expect(existingInstall(gone, edit)).toBeNull();
    expect(openIssues(gone, edit)).toHaveLength(1);
  });

  it("plans into the picked install and installs into the one the plan names", () => {
    const edit = bundleEditReducer(initialEdit(preview(), models), {
      type: "deployInto",
      id: "Research kit",
    });
    const draft = buildInstallRequest(preview(), edit, true);
    expect(draft.install_id).toBe("Research kit");
    const analyze = analyzeRequestFor(draft);
    expect(analyze.into).toBe("Research kit");
    expect("install_id" in analyze).toBe(false);
    expect(
      planKey(draft) !==
        planKey(
          buildInstallRequest(preview(), initialEdit(preview(), models), true)
        )
    ).toBe(true);

    const plan: ImportPreview = {
      ...preview(),
      plan_digest: "d1",
      install: {
        id: "inst-1",
        name: "Research kit",
        updated_at: existing.updated_at,
      },
    };
    expect(installRequestFor(draft, plan)).toMatchObject({
      plan_digest: "d1",
      install_id: "inst-1",
    });
    expect(installRequestFor(draft, { ...plan, plan_digest: null })).toBeNull();
  });

  it("creates a new install when nothing was picked", () => {
    const draft = buildInstallRequest(
      preview(),
      initialEdit(preview(), models),
      true
    );
    expect(analyzeRequestFor(draft).into).toBeUndefined();
    expect(
      installRequestFor(draft, { ...preview(), plan_digest: "d0" })?.install_id
    ).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import type { EvalRunDetail } from "@/api/client/types.gen";
import {
  buildRunMatrix,
  candidateGate,
  checkFromForm,
  checkValue,
  percent,
  usd,
} from "./evals";

function trial(
  caseId: string,
  arm: string,
  attempt: number,
  passed: boolean | null
) {
  return {
    id: `${caseId}-${arm}-${attempt}`,
    case_id: caseId,
    arm,
    attempt,
    task_id: null,
    status: passed === null ? "running" : "done",
    passed,
    check_results: [],
    cost_usd: "0",
    error: null,
  };
}

function run(
  trials: ReturnType<typeof trial>[],
  withCandidate = true
): EvalRunDetail {
  return {
    id: "r",
    suite_id: "s",
    agent_id: "a",
    baseline_revision_id: "b",
    candidate_revision_id: withCandidate ? "c" : null,
    trials: 2,
    concurrency: 1,
    budget_usd: "1",
    cost_usd: "0",
    status: "completed",
    stop_reason: null,
    summary: {},
    started_at: null,
    completed_at: null,
    created_at: "2026-10-03T00:00:00Z",
    trials_detail: trials,
    cases: [
      {
        id: "k1",
        suite_id: "s",
        name: "greets",
        input: "hi",
        parameters: {},
        checks: [],
        stubs: {},
        source_task_id: null,
        created_at: "",
      },
      {
        id: "k2",
        suite_id: "s",
        name: "refunds",
        input: "refund",
        parameters: {},
        checks: [],
        stubs: {},
        source_task_id: null,
        created_at: "",
      },
    ],
  } as unknown as EvalRunDetail;
}

describe("buildRunMatrix", () => {
  it("marks a case that passes on the baseline and not on the candidate as a regression", () => {
    const rows = buildRunMatrix(
      run([
        trial("k1", "baseline", 1, true),
        trial("k1", "baseline", 2, true),
        trial("k1", "candidate", 1, true),
        trial("k1", "candidate", 2, false),
        trial("k2", "baseline", 1, false),
        trial("k2", "candidate", 1, true),
      ])
    );

    expect(rows.map((r) => [r.name, r.verdict])).toEqual([
      ["greets", "regression"],
      ["refunds", "improvement"],
    ]);
    expect(rows[0].baseline).toMatchObject({ passed: 2, total: 2, pass: true });
    expect(rows[0].candidate).toMatchObject({
      passed: 1,
      total: 2,
      pass: false,
    });
  });

  it("leaves a case with unfinished trials undecided", () => {
    const rows = buildRunMatrix(run([trial("k1", "baseline", 1, null)], false));

    expect(rows[0].baseline.pass).toBeNull();
    expect(rows[0].candidate).toBeNull();
    expect(rows[0].verdict).toBe("pending");
  });
});

describe("checkFromForm", () => {
  it("builds the contract shape for each kind", () => {
    expect(checkFromForm("response_contains", "refund")).toEqual({
      type: "response_contains",
      text: "refund",
    });
    expect(checkFromForm("max_cost", "0.25")).toEqual({
      type: "max_cost",
      usd: 0.25,
    });
    expect(checkFromForm("max_iterations", "8")).toEqual({
      type: "max_iterations",
      count: 8,
    });
    expect(checkFromForm("artifact_exists", "*.pptx")).toEqual({
      type: "artifact_exists",
      glob: "*.pptx",
    });
  });

  it("refuses an empty or unparsable value", () => {
    expect(checkFromForm("response_contains", "  ")).toBeNull();
    expect(checkFromForm("max_cost", "cheap")).toBeNull();
    expect(checkFromForm("max_iterations", "2.5")).toBeNull();
  });

  it("reads the value back for display", () => {
    expect(checkValue({ type: "tool_called", tool: "shell_bash" })).toBe(
      "shell_bash"
    );
    expect(checkValue({ type: "max_cost", usd: 0.5 })).toBe("$0.5");
  });
});

describe("percent", () => {
  it("formats a share and a missing value", () => {
    expect(percent(0.256)).toBe("26%");
    expect(percent(null)).toBe("—");
  });
});

describe("usd", () => {
  it("keeps sub-cent spend visible", () => {
    expect(usd("0.000312")).toBe("$0.0003");
    expect(usd(1.5)).toBe("$1.50");
    expect(usd(0)).toBe("$0.00");
    expect(usd(null)).toBe("—");
  });
});

describe("candidateGate", () => {
  const evalRun = (
    candidate: string | null,
    status: string,
    completedAt: string | null,
    passed?: boolean
  ) =>
    ({
      candidate_revision_id: candidate,
      status,
      completed_at: completedAt,
      summary: passed === undefined ? {} : { passed },
    }) as unknown as EvalRunDetail;

  it("follows the latest completed run of that candidate", () => {
    const runs = [
      evalRun("v2", "completed", "2026-10-03T10:00:00Z", true),
      evalRun("v2", "completed", "2026-10-03T12:00:00Z", false),
      evalRun("v2", "running", null),
      evalRun("v3", "completed", "2026-10-03T13:00:00Z", true),
    ];
    expect(candidateGate(runs, "v2")).toBe("failed");
    expect(candidateGate(runs, "v3")).toBe("passed");
    expect(candidateGate(runs, "v4")).toBe("missing");
  });
});

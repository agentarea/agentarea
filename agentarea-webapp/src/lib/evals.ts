// Shaping evaluation data for display: run matrices, check forms, shares.

import type { EvalRunDetail, EvalTrialResponse } from "@/api/client/types.gen";

export type ArmCell = {
  passed: number;
  total: number;
  /** pass^k: every trial passed. ``null`` while any trial is unfinished. */
  pass: boolean | null;
  trials: EvalTrialResponse[];
};

export type CaseVerdict =
  | "regression"
  | "improvement"
  | "pass"
  | "fail"
  | "pending";

export type RunMatrixRow = {
  caseId: string;
  name: string;
  baseline: ArmCell;
  candidate: ArmCell | null;
  verdict: CaseVerdict;
};

function cell(trials: EvalTrialResponse[]): ArmCell {
  const finished = trials.filter(
    (t) => t.passed !== null && t.passed !== undefined
  );
  const passed = finished.filter((t) => t.passed === true).length;
  const pass =
    trials.length === 0 || finished.length < trials.length
      ? null
      : passed === trials.length;
  return {
    passed,
    total: trials.length,
    pass,
    trials: [...trials].sort((a, b) => a.attempt - b.attempt),
  };
}

function verdict(baseline: ArmCell, candidate: ArmCell | null): CaseVerdict {
  if (baseline.pass === null || (candidate && candidate.pass === null)) {
    return "pending";
  }
  if (!candidate) return baseline.pass ? "pass" : "fail";
  if (baseline.pass && !candidate.pass) return "regression";
  if (!baseline.pass && candidate.pass) return "improvement";
  return candidate.pass ? "pass" : "fail";
}

export function buildRunMatrix(run: EvalRunDetail): RunMatrixRow[] {
  const hasCandidate = Boolean(run.candidate_revision_id);
  return run.cases.map((testCase) => {
    const ofCase = run.trials_detail.filter((t) => t.case_id === testCase.id);
    const baseline = cell(ofCase.filter((t) => t.arm === "baseline"));
    const candidate = hasCandidate
      ? cell(ofCase.filter((t) => t.arm === "candidate"))
      : null;
    return {
      caseId: testCase.id,
      name: testCase.name,
      baseline,
      candidate,
      verdict: verdict(baseline, candidate),
    };
  });
}

export const CHECK_KINDS = [
  "response_contains",
  "response_not_contains",
  "response_matches",
  "tool_called",
  "tool_not_called",
  "artifact_exists",
  "max_cost",
  "max_iterations",
  "status_is",
] as const;

export type CheckKind = (typeof CHECK_KINDS)[number];

export type Check = { type: string } & Record<string, unknown>;

const FIELD: Record<CheckKind, string> = {
  response_contains: "text",
  response_not_contains: "text",
  response_matches: "pattern",
  tool_called: "tool",
  tool_not_called: "tool",
  artifact_exists: "glob",
  max_cost: "usd",
  max_iterations: "count",
  status_is: "status",
};

/** The contract shape of one check, or ``null`` when the value cannot be one. */
export function checkFromForm(kind: CheckKind, raw: string): Check | null {
  const value = raw.trim();
  if (!value) return null;
  if (kind === "max_cost") {
    const usd = Number(value);
    return Number.isFinite(usd) && usd >= 0 ? { type: kind, usd } : null;
  }
  if (kind === "max_iterations") {
    const count = Number(value);
    return Number.isInteger(count) && count >= 0 ? { type: kind, count } : null;
  }
  return { type: kind, [FIELD[kind]]: value };
}

export function checkValue(check: Check): string {
  const kind = check.type as CheckKind;
  const value = check[FIELD[kind] ?? ""];
  if (kind === "max_cost") return `$${String(value)}`;
  return value === undefined ? "" : String(value);
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function usd(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return "—";
  return `$${amount.toFixed(amount > 0 && amount < 0.01 ? 4 : 2)}`;
}

export type CandidateGate = "passed" | "failed" | "missing";

type GateRun = Pick<
  EvalRunDetail,
  "candidate_revision_id" | "status" | "completed_at" | "summary"
>;

export function candidateGate(
  runs: GateRun[],
  candidateId: string
): CandidateGate {
  const latest = runs
    .filter(
      (run) =>
        run.candidate_revision_id === candidateId &&
        run.status === "completed" &&
        run.completed_at
    )
    .sort((a, b) =>
      (b.completed_at ?? "").localeCompare(a.completed_at ?? "")
    )[0];
  if (!latest) return "missing";
  return (latest.summary as { passed?: boolean }).passed === true
    ? "passed"
    : "failed";
}

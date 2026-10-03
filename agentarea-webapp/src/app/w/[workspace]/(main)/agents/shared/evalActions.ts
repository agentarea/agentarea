"use server";

import type {
  CaseCreate,
  DecisionResponse,
  EvalRunCreate,
  ExperimentCreate,
  FieldChange,
  RevisionCreate,
} from "@/api/client/types.gen";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  activateRevision,
  addCase,
  addCaseFromTask,
  createCandidateRevision,
  createSuite,
  deleteCase,
  deleteSuite,
  diffRevision,
  evaluateExperiment,
  promoteExperiment,
  rateRun,
  startEvalRun,
  startExperiment,
  stopEvalRun,
  stopExperiment,
} from "@/lib/api-evals";

export type ActionResult<T = null> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function done<T>(
  result: { data?: T; error?: unknown; status?: number },
  label: string
): ActionResult<T> {
  if (result.error !== undefined && result.error !== null) {
    return { ok: false, error: apiErrorMessage(result, label) };
  }
  return { ok: true, data: result.data as T };
}

export async function diffRevisionAction(
  agentId: string,
  revisionId: string,
  against?: string
): Promise<ActionResult<FieldChange[]>> {
  return done(
    await diffRevision(agentId, revisionId, against),
    "Could not load the diff"
  );
}

export async function createCandidateAction(
  agentId: string,
  body: RevisionCreate
): Promise<ActionResult<{ id: string; number: number }>> {
  const result = done(
    await createCandidateRevision(agentId, body),
    "Could not create the candidate"
  );
  return result.ok
    ? { ok: true, data: { id: result.data.id, number: result.data.number } }
    : result;
}

export async function activateRevisionAction(
  agentId: string,
  revisionId: string
): Promise<ActionResult<null>> {
  const result = done(
    await activateRevision(agentId, revisionId),
    "Could not serve this revision"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function startExperimentAction(
  agentId: string,
  body: ExperimentCreate
): Promise<ActionResult<null>> {
  const result = done(
    await startExperiment(agentId, body),
    "Could not start the experiment"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function evaluateExperimentAction(
  agentId: string,
  experimentId: string
): Promise<ActionResult<DecisionResponse | null>> {
  return done(
    await evaluateExperiment(agentId, experimentId),
    "Could not evaluate the experiment"
  );
}

export async function stopExperimentAction(
  agentId: string,
  experimentId: string
): Promise<ActionResult<null>> {
  const result = done(
    await stopExperiment(agentId, experimentId),
    "Could not stop the experiment"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function promoteExperimentAction(
  agentId: string,
  experimentId: string
): Promise<ActionResult<null>> {
  const result = done(
    await promoteExperiment(agentId, experimentId),
    "Could not promote the candidate"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function createSuiteAction(
  name: string,
  description: string
): Promise<ActionResult<{ id: string }>> {
  const result = done(
    await createSuite({ name, description: description || null }),
    "Could not create the suite"
  );
  return result.ok ? { ok: true, data: { id: result.data.id } } : result;
}

export async function deleteSuiteAction(
  suiteId: string
): Promise<ActionResult<null>> {
  const result = done(await deleteSuite(suiteId), "Could not delete the suite");
  return result.ok ? { ok: true, data: null } : result;
}

export async function addCaseAction(
  suiteId: string,
  body: CaseCreate
): Promise<ActionResult<null>> {
  const result = done(await addCase(suiteId, body), "Could not add the case");
  return result.ok ? { ok: true, data: null } : result;
}

export async function addCaseFromTaskAction(
  suiteId: string,
  taskId: string
): Promise<ActionResult<null>> {
  const result = done(
    await addCaseFromTask(suiteId, taskId),
    "Could not add the run to the suite"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function deleteCaseAction(
  suiteId: string,
  caseId: string
): Promise<ActionResult<null>> {
  const result = done(
    await deleteCase(suiteId, caseId),
    "Could not delete the case"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function startEvalRunAction(
  agentId: string,
  body: EvalRunCreate
): Promise<ActionResult<{ id: string }>> {
  const result = done(
    await startEvalRun(agentId, body),
    "Could not start the evaluation"
  );
  return result.ok ? { ok: true, data: { id: result.data.id } } : result;
}

export async function stopEvalRunAction(
  agentId: string,
  runId: string
): Promise<ActionResult<null>> {
  const result = done(
    await stopEvalRun(agentId, runId),
    "Could not stop the evaluation"
  );
  return result.ok ? { ok: true, data: null } : result;
}

export async function rateRunAction(
  taskId: string,
  rating: "good" | "bad",
  comment: string
): Promise<ActionResult<null>> {
  const result = done(
    await rateRun(taskId, { rating, comment: comment || null }),
    "Could not save your rating"
  );
  return result.ok ? { ok: true, data: null } : result;
}

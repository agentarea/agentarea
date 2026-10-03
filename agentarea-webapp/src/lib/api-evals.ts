// Agent revisions, experiments, evaluation suites and runs, run feedback.

import { client as serverClient } from "@/api/client/client.gen";
import * as sdk from "@/api/client/sdk.gen";
import type {
  CaseCreate,
  EvalRunCreate,
  ExperimentCreate,
  FeedbackCreate,
  RevisionCreate,
  SuiteCreate,
} from "@/api/client/types.gen";

function withStatus<TData, TError>(result: {
  data?: TData;
  error?: TError;
  response?: Response;
}) {
  return {
    data: result.data,
    error: result.error,
    status: result.response?.status,
  };
}

const agentPath = (agentId: string) => ({ agent_id: agentId });

export const listRevisions = async (agentId: string) =>
  withStatus(
    await sdk.listRevisionsV1AgentsAgentIdRevisionsGet({
      client: serverClient,
      path: agentPath(agentId),
    })
  );

export const listRevisionOutcomes = async (agentId: string) =>
  withStatus(
    await sdk.revisionOutcomesV1AgentsAgentIdRevisionsOutcomesGet({
      client: serverClient,
      path: agentPath(agentId),
    })
  );

export const diffRevision = async (
  agentId: string,
  revisionId: string,
  against?: string
) =>
  withStatus(
    await sdk.diffRevisionV1AgentsAgentIdRevisionsRevisionIdDiffGet({
      client: serverClient,
      path: { agent_id: agentId, revision_id: revisionId },
      query: against ? { against } : undefined,
    })
  );

export const createCandidateRevision = async (
  agentId: string,
  body: RevisionCreate
) =>
  withStatus(
    await sdk.createCandidateV1AgentsAgentIdRevisionsPost({
      client: serverClient,
      path: agentPath(agentId),
      body,
    })
  );

export const activateRevision = async (agentId: string, revisionId: string) =>
  withStatus(
    await sdk.activateRevisionV1AgentsAgentIdRevisionsRevisionIdActivatePost({
      client: serverClient,
      path: { agent_id: agentId, revision_id: revisionId },
    })
  );

export const listExperiments = async (agentId: string) =>
  withStatus(
    await sdk.listExperimentsV1AgentsAgentIdExperimentsGet({
      client: serverClient,
      path: agentPath(agentId),
    })
  );

export const startExperiment = async (
  agentId: string,
  body: ExperimentCreate
) =>
  withStatus(
    await sdk.startExperimentV1AgentsAgentIdExperimentsPost({
      client: serverClient,
      path: agentPath(agentId),
      body,
    })
  );

export const evaluateExperiment = async (
  agentId: string,
  experimentId: string
) =>
  withStatus(
    await sdk.evaluateExperimentV1AgentsAgentIdExperimentsExperimentIdEvaluatePost(
      {
        client: serverClient,
        path: { agent_id: agentId, experiment_id: experimentId },
      }
    )
  );

export const stopExperiment = async (agentId: string, experimentId: string) =>
  withStatus(
    await sdk.stopExperimentV1AgentsAgentIdExperimentsExperimentIdStopPost({
      client: serverClient,
      path: { agent_id: agentId, experiment_id: experimentId },
    })
  );

export const promoteExperiment = async (
  agentId: string,
  experimentId: string
) =>
  withStatus(
    await sdk.promoteExperimentV1AgentsAgentIdExperimentsExperimentIdPromotePost(
      {
        client: serverClient,
        path: { agent_id: agentId, experiment_id: experimentId },
      }
    )
  );

export const listSuites = async () =>
  withStatus(await sdk.listSuitesV1EvalSuitesGet({ client: serverClient }));

export const createSuite = async (body: SuiteCreate) =>
  withStatus(
    await sdk.createSuiteV1EvalSuitesPost({ client: serverClient, body })
  );

export const deleteSuite = async (suiteId: string) =>
  withStatus(
    await sdk.deleteSuiteV1EvalSuitesSuiteIdDelete({
      client: serverClient,
      path: { suite_id: suiteId },
    })
  );

export const listCases = async (suiteId: string) =>
  withStatus(
    await sdk.listCasesV1EvalSuitesSuiteIdCasesGet({
      client: serverClient,
      path: { suite_id: suiteId },
    })
  );

export const addCase = async (suiteId: string, body: CaseCreate) =>
  withStatus(
    await sdk.addCaseV1EvalSuitesSuiteIdCasesPost({
      client: serverClient,
      path: { suite_id: suiteId },
      body,
    })
  );

export const addCaseFromTask = async (
  suiteId: string,
  taskId: string,
  name?: string
) =>
  withStatus(
    await sdk.addCaseFromTaskV1EvalSuitesSuiteIdCasesFromTaskPost({
      client: serverClient,
      path: { suite_id: suiteId },
      body: { task_id: taskId, name: name ?? null },
    })
  );

export const deleteCase = async (suiteId: string, caseId: string) =>
  withStatus(
    await sdk.deleteCaseV1EvalSuitesSuiteIdCasesCaseIdDelete({
      client: serverClient,
      path: { suite_id: suiteId, case_id: caseId },
    })
  );

export const listEvalRuns = async (agentId: string) =>
  withStatus(
    await sdk.listRunsV1AgentsAgentIdEvalRunsGet({
      client: serverClient,
      path: agentPath(agentId),
    })
  );

export const startEvalRun = async (agentId: string, body: EvalRunCreate) =>
  withStatus(
    await sdk.startRunV1AgentsAgentIdEvalRunsPost({
      client: serverClient,
      path: agentPath(agentId),
      body,
    })
  );

export const getEvalRun = async (agentId: string, runId: string) =>
  withStatus(
    await sdk.getRunV1AgentsAgentIdEvalRunsRunIdGet({
      client: serverClient,
      path: { agent_id: agentId, run_id: runId },
    })
  );

export const stopEvalRun = async (agentId: string, runId: string) =>
  withStatus(
    await sdk.stopRunV1AgentsAgentIdEvalRunsRunIdStopPost({
      client: serverClient,
      path: { agent_id: agentId, run_id: runId },
    })
  );

export const listRunFeedback = async (taskId: string) =>
  withStatus(
    await sdk.listFeedbackV1TasksTaskIdFeedbackGet({
      client: serverClient,
      path: { task_id: taskId },
    })
  );

export const rateRun = async (taskId: string, body: FeedbackCreate) =>
  withStatus(
    await sdk.rateRunV1TasksTaskIdFeedbackPut({
      client: serverClient,
      path: { task_id: taskId },
      body,
    })
  );

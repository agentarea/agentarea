import type { Metadata } from "next";
import type { FeedbackResponse, SuiteResponse } from "@/api/client/types.gen";
import { getAgent, getAgentTaskById } from "@/lib/api";
import { listRunFeedback, listSuites } from "@/lib/api-evals";
import { getAuthContext } from "@/lib/getAuthContext";
import { requireApiData } from "@/lib/server-resource";
import AgentTaskClient from "./AgentTaskClient";
import RunFeedbackBar from "./RunFeedbackBar";

export const metadata: Metadata = {
  title: "Task Details",
};

interface Props {
  params: Promise<{ id: string; taskId: string }>;
}

export default async function AgentTaskPage({ params }: Props) {
  const { id, taskId } = await params;

  // Load both agent and task data
  const [agentResponse, taskResponse, feedbackResponse, suitesResponse, auth] =
    await Promise.all([
      getAgent(id),
      getAgentTaskById(id, taskId),
      listRunFeedback(taskId),
      listSuites(),
      getAuthContext(),
    ]);

  const agent = requireApiData(agentResponse, "agent");
  const task = requireApiData(taskResponse, "task");
  const feedback = (feedbackResponse.data ?? []) as FeedbackResponse[];
  const mine = feedback.find((f) => f.created_by === auth?.userId) ?? null;

  return (
    <AgentTaskClient
      agent={agent}
      taskId={taskId}
      task={task}
      feedback={
        <RunFeedbackBar
          taskId={taskId}
          mine={mine}
          suites={(suitesResponse.data ?? []) as SuiteResponse[]}
        />
      }
    />
  );
}

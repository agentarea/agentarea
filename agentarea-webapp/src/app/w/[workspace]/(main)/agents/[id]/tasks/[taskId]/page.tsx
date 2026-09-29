import type { Metadata } from "next";
import { getAgent, getAgentTaskById } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import AgentTaskClient from "./AgentTaskClient";

export const metadata: Metadata = {
  title: "Task Details",
};

interface Props {
  params: Promise<{ id: string; taskId: string }>;
}

export default async function AgentTaskPage({ params }: Props) {
  const { id, taskId } = await params;

  // Load both agent and task data
  const [agentResponse, taskResponse] = await Promise.all([
    getAgent(id),
    getAgentTaskById(id, taskId),
  ]);

  const agent = requireApiData(agentResponse, "agent");
  const task = requireApiData(taskResponse, "task");

  return <AgentTaskClient agent={agent} taskId={taskId} task={task} />;
}

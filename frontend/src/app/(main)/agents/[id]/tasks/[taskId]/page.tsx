import { notFound } from "next/navigation";
import { getAgent, getAgentTaskById } from "@/lib/api";
import AgentTaskClient from "./AgentTaskClient";

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

  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;
  const task = taskResponse.data;

  return <AgentTaskClient agent={agent} taskId={taskId} task={task} />;
}

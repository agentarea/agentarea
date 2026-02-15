import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { getAgent, getAgentTaskById } from "@/lib/api";
import AgentTaskClient from "./AgentTaskClient";

interface Props {
  params: Promise<{ id: string; taskId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id, taskId } = await params;
  const task = await getAgentTaskById(id, taskId);
  const t = await getTranslations("Metadata");
  const description = task.data?.description || "Task";
  const truncatedDesc = description.length > 30 ? description.substring(0, 30) + "..." : description;
  return {
    title: t("taskDetail", { description: truncatedDesc }),
  };
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

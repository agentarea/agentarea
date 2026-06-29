import type { Metadata } from "next";
import { Suspense } from "react";
import { notFound } from "next/navigation";
import { getAgent, listAgentTasks, type Agent } from "@/lib/api";
import AgentTasksList from "./components/AgentTasksList";
import AgentTasksSkeleton from "./components/AgentTasksSkeleton";
import { TaskWithStatus } from "./types";

export const metadata: Metadata = {
  title: "Agent Tasks",
};

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentTasksPage({ params }: Props) {
  const { id } = await params;

  const agentRes = await getAgent(id);
  const agent = agentRes.data as Agent | undefined;
  if (!agent) notFound();
  const realId = agent.id;

  let initialTasks: TaskWithStatus[] = [];
  try {
    const { data: tasksData, error } = await listAgentTasks(realId);
    if (!error && tasksData) {
      initialTasks = tasksData.map((task: TaskWithStatus) => ({
        ...task,
        taskStatus: undefined,
      }));
    }
  } catch (error) {
    console.error("Failed to load initial tasks:", error);
  }

  return (
    <Suspense fallback={<AgentTasksSkeleton />}>
      <AgentTasksList agentId={realId} initialTasks={initialTasks} />
    </Suspense>
  );
}

import { notFound } from "next/navigation";
import { getAgent } from "@/lib/api";
import AgentNewTask from "./components/AgentNewTask";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentNewTaskPage({ params }: Props) {
  const { id } = await params;
  const agentResponse = await getAgent(id);
  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;
  return <AgentNewTask agent={agent} />;
}



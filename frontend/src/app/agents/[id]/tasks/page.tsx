import AgentTasksList from "./components/AgentTasksList";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentTasksPage({ params }: Props) {
  const { id } = await params;
  return <AgentTasksList agentId={id} />;
}



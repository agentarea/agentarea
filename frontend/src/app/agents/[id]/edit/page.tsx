import { notFound } from 'next/navigation';
import { getAgent, listMCPServers, listModelInstances } from '@/lib/api';
import EditAgentClient from './EditAgentClient';
import ContentBlock from '@/components/ContentBlock/ContentBlock';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditAgentPage({ params }: Props) {
  const { id } = await params;
  try {
    const [agentResponse, mcpResponse, llmResponse] = await Promise.all([
      getAgent(id),
      listMCPServers(),
      listModelInstances(),
    ]);

    if (!agentResponse.data) {
      notFound();
    }

    const agent = agentResponse.data;
    const mcpServers = (mcpResponse.data || []).map((server: any) => ({
      ...server,
      status: ["published", "draft", "pending", "rejected"].includes(server.status)
        ? server.status
        : "draft",
    }));
    const llmModelInstances = llmResponse.data || [];

    return (
      <ContentBlock 
        header={{
          title: "Edit Agent",
          backLink: {
            label: "Back to Browse Agents",
            href: "/agents"
          }
        }}>
        <EditAgentClient 
          agent={agent}
          mcpServers={mcpServers} 
          llmModelInstances={llmModelInstances} 
        />
      </ContentBlock>
    );
  } catch (error) {
    console.error('Error loading agent:', error);
    notFound();
  }
}
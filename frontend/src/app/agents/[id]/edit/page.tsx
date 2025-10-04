import { notFound } from 'next/navigation';
import { getAgent, listMCPServers, listModelInstances, listMCPServerInstances, listBuiltinTools } from '@/lib/api';
import EditAgentClient from './EditAgentClient';
import ContentBlock from '@/components/ContentBlock/ContentBlock';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditAgentPage({ params }: Props) {
  const { id } = await params;
  try {
    const [agentResponse, mcpResponse, llmResponse, mcpInstancesResponse, builtinToolsResponse] = await Promise.all([
      getAgent(id),
      listMCPServers(),
      listModelInstances(),
      listMCPServerInstances(),
      listBuiltinTools(),
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
    const mcpInstanceList = mcpInstancesResponse.data || [];
    const builtinTools = Array.isArray(builtinToolsResponse.data)
      ? builtinToolsResponse.data
      : Object.values(builtinToolsResponse.data || {});

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
          mcpInstanceList={mcpInstanceList}
          builtinTools={builtinTools}
        />
      </ContentBlock>
    );
  } catch (error) {
    console.error('Error loading agent:', error);
    notFound();
  }
}
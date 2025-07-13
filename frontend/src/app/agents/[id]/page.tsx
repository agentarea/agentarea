import { notFound } from 'next/navigation';
import { getAgent } from '@/lib/api';
import AgentDetailClient from './AgentDetailClient';
import ContentBlock from '@/components/ContentBlock/ContentBlock';

interface Props {
  params: { id: string };
}

export default async function AgentDetailPage({ params }: Props) {
  try {
    const agentResponse = await getAgent(params.id);

    if (!agentResponse.data) {
      notFound();
    }

    const agent = agentResponse.data;

    return (
      <ContentBlock 
        header={{
          title: agent.name,
          description: agent.description || "Agent details and interaction",
          backLink: {
            label: "Back to Browse Agents",
            href: "/agents/browse"
          }
        }}>
        <AgentDetailClient agent={agent} />
      </ContentBlock>
    );
  } catch (error) {
    console.error('Error loading agent:', error);
    notFound();
  }
} 
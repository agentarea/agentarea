'use client';

import { deleteAgent } from '@/lib/api';
import DeleteButton from '@/components/DeleteButton';

interface DeleteAgentButtonProps {
  agentId: string;
  agentName: string;
}

export default function DeleteAgentButton({ agentId, agentName }: DeleteAgentButtonProps) {
  return (
    <DeleteButton
      itemId={agentId}
      itemName={agentName}
      onDelete={deleteAgent}
      redirectPath="/agents/browse"
      title="Delete Agent"
      successMessage="Agent deleted successfully"
      errorMessages={{
        noIdProvided: 'No agent ID provided',
        failedToDelete: 'Failed to delete agent',
        unexpectedError: 'Unexpected error while deleting agent'
      }}
    />
  );
}

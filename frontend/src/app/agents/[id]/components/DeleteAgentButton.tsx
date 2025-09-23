'use client';

import { deleteAgent } from '@/lib/api';
import DeleteButton from '@/components/DeleteButton';
import { useTranslations } from 'next-intl';

interface DeleteAgentButtonProps {
  agentId: string;
  agentName: string;
}

export default function DeleteAgentButton({ agentId, agentName }: DeleteAgentButtonProps) {
  const t = useTranslations("Agent.delete");
  return (
    <DeleteButton
      itemId={agentId}
      itemName={agentName}
      onDelete={deleteAgent}
      redirectPath="/agents"
      title={t("deleteAgent")}
      successMessage={t("agentDeletedSuccessfully")}
      errorMessages={{
        noIdProvided: t("error.noAgentIdProvided"),
        failedToDelete: t("error.failedToDeleteAgent"),
        unexpectedError: t("error.unexpectedErrorWhileDeletingAgent")
      }}
    />
  );
}

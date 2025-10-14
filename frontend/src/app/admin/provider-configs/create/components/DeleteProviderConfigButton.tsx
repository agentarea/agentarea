'use client';

import { deleteProviderConfig } from '../../actions';
import DeleteButton from '@/components/DeleteButton';
import { useTranslations } from 'next-intl';

interface DeleteProviderConfigButtonProps {
  configId: string;
  configName: string;
}

export default function DeleteProviderConfigButton({ configId, configName }: DeleteProviderConfigButtonProps) {
  const t = useTranslations("Models");
  const tProviderConfigForm = useTranslations("ProviderConfigForm");

  return (
    <DeleteButton
      itemId={configId}
      itemName={configName}
      onDelete={deleteProviderConfig}
      redirectPath="/admin/provider-configs"
      title={t("deleteProviderConfiguration")}
      description={t("deleteProviderConfigurationDescription", { configName })}
      successMessage={tProviderConfigForm("toast.configurationDeleted")}
      errorMessages={{
        noIdProvided: t("error.noConfigIdProvided"),
        failedToDelete: t("error.failedToDeleteConfiguration"),
        unexpectedError: t("error.unexpectedErrorWhileDeleting")
      }}
    />
  );
}

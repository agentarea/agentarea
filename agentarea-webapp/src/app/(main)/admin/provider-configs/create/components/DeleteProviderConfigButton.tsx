"use client";

import { useTranslations } from "next-intl";
import DeleteButton from "@/components/DeleteButton";
import { deleteProviderConfig } from "../../actions";

interface DeleteProviderConfigButtonProps {
  configId: string;
  configName: string;
}

export default function DeleteProviderConfigButton({
  configId,
  configName,
}: DeleteProviderConfigButtonProps) {
  const t = useTranslations("Models");
  const tProviderConfigForm = useTranslations("ProviderConfigForm");

  return (
    <DeleteButton
      itemId={configId}
      itemName={configName}
      onDelete={async (configId) => {
          const { error } = await deleteProviderConfig(configId);
          return { error: error as { detail?: Array<{ msg?: string }> } | undefined };
        }}
      redirectPath="/admin/provider-configs"
      title={t("deleteProviderConfiguration")}
      description={t("deleteProviderConfigurationDescription", { configName })}
      successMessage={tProviderConfigForm("toast.configurationDeleted")}
      errorMessages={{
        noIdProvided: t("error.noConfigIdProvided"),
        failedToDelete: t("error.failedToDeleteConfiguration"),
        unexpectedError: t("error.unexpectedErrorWhileDeleting"),
      }}
    />
  );
}

import { getTranslations } from "next-intl/server";
import ProviderConfigForm from "@/components/ProviderConfigForm";
import { getProviderConfig, listModelInstances } from "@/lib/api";

interface ProviderConfigFormWrapperProps {
  preselectedProviderId?: string;
  isEdit: boolean;
}

export default async function ProviderConfigFormWrapper({
  preselectedProviderId,
  isEdit,
}: ProviderConfigFormWrapperProps) {
  const t = await getTranslations("Models");

  // Load initial data if in edit mode
  let initialData = undefined;
  let existingModelInstances: any[] = [];

  if (isEdit && preselectedProviderId) {
    try {
      const [configResponse, instancesResponse] = await Promise.all([
        getProviderConfig(preselectedProviderId),
        listModelInstances({
          provider_config_id: preselectedProviderId,
          is_active: true,
        }),
      ]);

      initialData = configResponse;
      existingModelInstances = instancesResponse.data || [];
    } catch (error) {
      console.error("Failed to load provider config for editing:", error);
      return (
        <div className="py-10 text-center">
          <p className="text-red-500">{t("error.loadingDataEdit")}</p>
        </div>
      );
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl">
      <ProviderConfigForm
        preselectedProviderId={preselectedProviderId}
        isEdit={isEdit}
        initialData={initialData}
        existingModelInstances={existingModelInstances}
      />
    </div>
  );
}

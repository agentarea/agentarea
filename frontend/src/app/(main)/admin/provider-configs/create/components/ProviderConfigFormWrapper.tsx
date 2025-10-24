import { getProviderConfig, listModelInstances } from '@/lib/api';
import ProviderConfigForm from '@/components/ProviderConfigForm';
import { getTranslations } from 'next-intl/server';

interface ProviderConfigFormWrapperProps {
  preselectedProviderId?: string;
  isEdit: boolean;
}

export default async function ProviderConfigFormWrapper({ 
  preselectedProviderId, 
  isEdit 
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
          is_active: true
        })
      ]);
      
      initialData = configResponse;
      existingModelInstances = instancesResponse.data || [];
    } catch (error) {
      console.error('Failed to load provider config for editing:', error);
      return (
        <div className="text-center py-10">
          <p className="text-red-500">
            {t("error.loadingDataEdit")}
          </p>
        </div>
      );
    }
  }

  return (
    <div className="max-w-4xl mx-auto w-full">
      <ProviderConfigForm 
        preselectedProviderId={preselectedProviderId}
        isEdit={isEdit}
        initialData={initialData}
        existingModelInstances={existingModelInstances}
      />
    </div>
  );
}


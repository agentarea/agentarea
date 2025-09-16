import { getProviderConfig, listModelInstances } from '@/lib/api';
import ProviderConfigForm from '@/components/ProviderConfigForm';
import ContentBlock from '@/components/ContentBlock/ContentBlock';
import DeleteButton from './components/DeleteButton';
import { getTranslations } from 'next-intl/server';

export default async function CreateProviderConfigPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const resolvedSearchParams = await searchParams;
  const t = await getTranslations("Models");  
  const tCommon = await getTranslations("Common");  
  
  // Get the provider_spec_id from query params if provided
  const preselectedProviderId = typeof resolvedSearchParams.provider_spec_id === 'string' 
    ? resolvedSearchParams.provider_spec_id 
    : undefined;

  // Check if this is edit mode
  const isEdit = resolvedSearchParams.isEdit === 'true';

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
    <ContentBlock 
      header={{
        breadcrumb: isEdit ? [
          {label: t("title"), href: "/admin/provider-configs"},
          {label: tCommon("edit")},
          {label:  `${initialData?.name}`}
        ] : [
          {label: t("title"), href: "/admin/provider-configs"},
          {label: tCommon("create")},
          {label:  t("configureProvider")}
        ],
        controls: isEdit && initialData ? (
          <DeleteButton 
            configId={initialData.id}
            configName={initialData.name}
          />
        ) : undefined
    }}>
      <div className="max-w-4xl mx-auto w-full">
        <ProviderConfigForm 
          preselectedProviderId={preselectedProviderId}
          isEdit={isEdit}
          initialData={initialData}
          existingModelInstances={existingModelInstances}
        />
      </div>
  </ContentBlock>
  );
} 
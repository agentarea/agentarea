import { getProviderConfig, listModelInstances } from '@/lib/api';
import ProviderConfigForm from '@/components/ProviderConfigForm';
import ContentBlock from '@/components/ContentBlock/ContentBlock';
import DeleteButton from './components/DeleteButton';

export default async function CreateProviderConfigPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const resolvedSearchParams = await searchParams;
  
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
      // Load provider config
      initialData = await getProviderConfig(preselectedProviderId);
      
      // Load existing model instances for this provider config
      const instancesResponse = await listModelInstances({
        provider_config_id: preselectedProviderId,
        is_active: true
      });
      
      if (instancesResponse.data) {
        existingModelInstances = instancesResponse.data;
      }
    } catch (error) {
      console.error('Failed to load provider config for editing:', error);
      // If we can't load the data, redirect back to the list
      return (
        <div className="text-center py-10">
          <p className="text-red-500">
            Failed to load provider configuration for editing. Please try again.
          </p>
        </div>
      );
    }
  }

  return (
    <ContentBlock 
      header={{
        breadcrumb: isEdit ? [
          {label: "Provider Management", href: "/admin/provider-configs"},
          {label: "Edit"},
          {label:  `${initialData?.name}`}
        ] : [
          {label: "Provider Management", href: "/admin/provider-configs"},
          {label: "Create"},
          {label:  "Provider Configuration"}
        ],
        controls: isEdit && initialData ? (
          <DeleteButton 
            configId={initialData.id}
            configName={initialData.name}
          />
        ) : undefined
    }}>
      <div className="max-w-4xl mx-auto">
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
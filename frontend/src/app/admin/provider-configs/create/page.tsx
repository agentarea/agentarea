import { listProviderSpecs, listProviderSpecsWithModels, getProviderConfig } from '@/lib/api';
import ProviderConfigForm from './ProviderConfigForm';
import ContentBlock from '@/components/ContentBlock/ContentBlock';
import DeleteButton from './DeleteButton';

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
  if (isEdit && preselectedProviderId) {
    try {
      initialData = await getProviderConfig(preselectedProviderId);
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

  // Fetch both provider specs and model specs
  const [providerSpecsResponse, providerSpecsWithModelsResponse] = await Promise.all([
    listProviderSpecs(),
    listProviderSpecsWithModels()
  ]);

  if (providerSpecsResponse.error || providerSpecsWithModelsResponse.error) {
    return (
      <div className="text-center py-10">
        <p className="text-red-500">
          Error loading provider specifications: {
            providerSpecsResponse.error?.detail?.[0]?.msg || 
            providerSpecsWithModelsResponse.error?.detail?.[0]?.msg ||
            'Unknown error occurred'
          }
        </p>
      </div>
    );
  }

  const providerSpecs = providerSpecsResponse.data || [];
  const providerSpecsWithModels = providerSpecsWithModelsResponse.data || [];
  
  // Extract and flatten model specs from the provider specs with models
  const modelSpecs = providerSpecsWithModels.flatMap(spec => 
    spec.models.map(model => ({
      id: model.id,
      provider_spec_id: spec.id,
      model_name: model.model_name,
      display_name: model.display_name,
      description: model.description || '',
      context_window: model.context_window,
      is_active: model.is_active,
    }))
  );

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
          providerSpecs={providerSpecs}
          modelSpecs={modelSpecs}
          preselectedProviderId={preselectedProviderId}
          isEdit={isEdit}
          initialData={initialData}
        />
      </div>
  </ContentBlock>
  );
} 
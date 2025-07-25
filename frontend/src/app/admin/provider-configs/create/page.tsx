import { listProviderSpecs, listProviderSpecsWithModels } from '@/lib/api';
import ProviderConfigForm from './ProviderConfigForm';
import ContentBlock from '@/components/ContentBlock/ContentBlock';

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
            providerSpecsResponse.error?.message || providerSpecsWithModelsResponse.error?.message
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
      description: model.description,
      context_window: model.context_window,
      is_active: model.is_active,
    }))
  );

  return (
    <ContentBlock 
      header={{
        breadcrumb: [
          {label: "Provider Management", href: "/admin/provider-configs"},
          {label: "Add Provider Configuration"},
        ],
    }}>
      <div className="max-w-4xl mx-auto">
        <ProviderConfigForm 
          providerSpecs={providerSpecs}
          modelSpecs={modelSpecs}
          preselectedProviderId={preselectedProviderId}
        />
      </div>
  </ContentBlock>
  );
} 
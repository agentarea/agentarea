import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { listProviderSpecs, listProviderSpecsWithModels } from '@/lib/api';
import ProviderConfigForm from './ProviderConfigForm';

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
    <div className="max-w-4xl mx-auto p-6">
      <div className="mb-6">
        <Link 
          href="/admin/provider-configs" 
          className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground mb-4"
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back to Provider Management
        </Link>
        
        <div className="space-y-2">
          <h1 className="text-2xl font-bold">
            {preselectedProviderId 
              ? `Configure ${providerSpecs.find(p => p.id === preselectedProviderId)?.name || 'Provider'}`
              : 'Add Provider Configuration'
            }
          </h1>
          <p className="text-muted-foreground">
            {preselectedProviderId 
              ? `Set up API access for ${providerSpecs.find(p => p.id === preselectedProviderId)?.name || 'this provider'} and optionally create model instances.`
              : 'Configure API access to an AI provider and optionally create model instances.'
            }
          </p>
        </div>
      </div>

      <ProviderConfigForm 
        providerSpecs={providerSpecs}
        modelSpecs={modelSpecs}
        preselectedProviderId={preselectedProviderId}
      />
    </div>
  );
} 
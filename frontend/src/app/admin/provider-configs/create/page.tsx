import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { listProviderSpecs, listProviderSpecsWithModels } from '@/lib/api';
import ProviderConfigForm from './ProviderConfigForm';

export default async function CreateProviderConfigPage() {
  // Fetch both provider specs and model specs
  const [providerSpecsResponse, providerSpecsWithModelsResponse] = await Promise.all([
    listProviderSpecs(),
    listProviderSpecsWithModels()
  ]);

  if (providerSpecsResponse.error || providerSpecsWithModelsResponse.error) {
    return (
      <div className="space-y-6">
        <div className="flex items-center space-x-4">
          <Link href="/admin/provider-configs" className="flex items-center text-gray-600 hover:text-gray-900">
            <ArrowLeft className="h-4 w-4 mr-1" />
            Back to Provider Configs
          </Link>
        </div>
        
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Add Provider Configuration</h1>
          <p className="text-gray-600 mt-2">Error loading provider data. Please try again.</p>
        </div>
      </div>
    );
  }

  const providerSpecs = providerSpecsResponse.data ?? [];
  const providerSpecsWithModels = providerSpecsWithModelsResponse.data ?? [];

  // Extract model specs from the provider specs with models
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
    <div className="space-y-6">
      <div className="flex items-center space-x-4">
        <Link href="/admin/provider-configs" className="flex items-center text-gray-600 hover:text-gray-900">
          <ArrowLeft className="h-4 w-4 mr-1" />
          Back to Provider Configs
        </Link>
      </div>
      
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Add Provider Configuration</h1>
        <p className="text-gray-600 mt-2">Configure API access to an AI provider and optionally create model instances.</p>
      </div>

      <ProviderConfigForm providerSpecs={providerSpecs} modelSpecs={modelSpecs} />
    </div>
  );
} 
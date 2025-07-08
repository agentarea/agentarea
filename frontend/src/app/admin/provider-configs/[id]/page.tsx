import { notFound } from 'next/navigation';
import { getProviderConfig, listProviderSpecs, listProviderSpecsWithModels } from '@/lib/api';
import ProviderConfigForm from '../create/ProviderConfigForm';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditProviderConfigPage({ params }: Props) {
  try {
    const resolvedParams = await params;
    
    const [providerConfigResponse, providerSpecsResponse, providerSpecsWithModelsResponse] = await Promise.all([
      getProviderConfig(resolvedParams.id),
      listProviderSpecs(),
      listProviderSpecsWithModels(),
    ]);

    if (providerConfigResponse.error || !providerConfigResponse.data) {
      notFound();
    }

    if (providerSpecsResponse.error || providerSpecsWithModelsResponse.error) {
      throw new Error('Failed to load provider specifications');
    }

    const providerConfig = providerConfigResponse.data;
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
            <h1 className="text-2xl font-bold">Edit Provider Configuration</h1>
            <p className="text-muted-foreground">
              Update your AI provider configuration settings
            </p>
          </div>
        </div>

        <ProviderConfigForm
          providerSpecs={providerSpecs}
          modelSpecs={modelSpecs}
          initialData={providerConfig}
          isEdit={true}
        />
      </div>
    );
  } catch (error) {
    console.error('Error loading provider config:', error);
    notFound();
  }
} 
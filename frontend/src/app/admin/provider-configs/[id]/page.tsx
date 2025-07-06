import { notFound } from 'next/navigation';
import { getProviderConfig, listProviderSpecs, listModelSpecs } from '@/lib/api';
import ProviderConfigForm from '../create/ProviderConfigForm';

interface Props {
  params: { id: string };
}

export default async function EditProviderConfigPage({ params }: Props) {
  try {
    const [providerConfig, providerSpecs, modelSpecs] = await Promise.all([
      getProviderConfig(params.id),
      listProviderSpecs(),
      listModelSpecs(),
    ]);

    if (!providerConfig) {
      notFound();
    }

    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Edit Provider Configuration</h1>
          <p className="text-gray-600 mt-2">
            Update your AI provider configuration and model assignments
          </p>
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
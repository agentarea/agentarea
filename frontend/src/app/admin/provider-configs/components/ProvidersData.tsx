import { listProviderConfigsWithModelInstances, listProviderSpecsWithModels } from "@/lib/api";
import { getTranslations } from 'next-intl/server';
import { ProviderSpec, ProviderConfig } from "./types";
import EmptyState from "@/components/EmptyState";
import { ProviderConfigCard, ProviderSpecCard } from "./ProviderItem";

interface ProvidersDataProps {
  searchQuery?: string;
}

export default async function ProvidersData({ searchQuery = "" }: ProvidersDataProps) {
    const t = await getTranslations("Models");

    // Fetch provider specs and configs with model instances
    const [specsResponse, configsResponse] = await Promise.all([
        listProviderSpecsWithModels(),
        listProviderConfigsWithModelInstances()
    ]);

    if (specsResponse.error || configsResponse.error) {
        const specsError = specsResponse.error as any;
        const configsError = configsResponse.error as any;
       
        return (
            <div className="text-center py-10">
                <p className="text-red-500">
                    {t("error.loadingData")}: {
                        specsError?.detail?.[0]?.msg || 
                        configsError?.detail?.[0]?.msg ||
                        'Unknown error occurred'
                    }
                </p>
            </div>
        );
    }

    const providerSpecs = (specsResponse.data || []) as ProviderSpec[];
    const providerConfigs = (configsResponse.data || []) as ProviderConfig[];

    // Filter provider specs based on search query
    let filteredProviderSpecs = providerSpecs;
    if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        filteredProviderSpecs = providerSpecs.filter(spec => 
            spec.name?.toLowerCase().includes(query) ||
            spec.provider_key?.toLowerCase().includes(query) ||
            spec.description?.toLowerCase().includes(query) ||
            spec.provider_type?.toLowerCase().includes(query)
        );
    }

    // Create a map of provider specs for easy lookup
    const specsMap = new Map(providerSpecs.map(spec => [spec.id, spec]));

    // Enhance configs with spec information
    const enhancedConfigs: ProviderConfig[] = providerConfigs.map(config => ({
        ...config,
        spec: specsMap.get(config.provider_spec_id)
    }));

    // Filter configs based on search query
    let filteredConfigs = enhancedConfigs;
    if (searchQuery.trim()) {
        const query = searchQuery.toLowerCase();
        filteredConfigs = enhancedConfigs.filter(config => 
            config.name?.toLowerCase().includes(query) ||
            config.spec?.name?.toLowerCase().includes(query) ||
            config.spec?.provider_key?.toLowerCase().includes(query) ||
            config.provider_spec_name?.toLowerCase().includes(query)
        );
    }

    // Check for empty states
    const hasNoConfigs = enhancedConfigs.length === 0;
    const hasNoSpecs = providerSpecs.length === 0;
    const hasNoData = hasNoConfigs && hasNoSpecs;
    const hasNoResults = filteredConfigs.length === 0 && filteredProviderSpecs.length === 0 && !hasNoData;

    if (hasNoData) {
        return (
            <EmptyState 
                title="No providers found"
                description="No provider configurations or specifications are available"
                iconsType="llm"
            />
        );
    }

    if (hasNoResults) {
        return (
            <EmptyState 
                title="No matching providers"
                description={`No providers match your search query: "${searchQuery}"`}
                iconsType="llm"
            />
        );
    }

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold mb-4">Provider Configs ({filteredConfigs.length})</h3>
                {filteredConfigs.length === 0 ? (
                    <div className="py-8">
                        <EmptyState 
                            title={hasNoConfigs ? "No provider configs" : "No matching configs"}
                            description={hasNoConfigs 
                                ? "No provider configurations are available" 
                                : `No configs match your search query: "${searchQuery}"`
                            }
                            iconsType="llm"
                        />
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
                        {
                            filteredConfigs.map((config) => (
                                <ProviderConfigCard key={config.id} config={config} />
                            ))
                        }
                    </div>
                )}
            </div>

            
            <div>
                <h3 className="text-lg font-semibold mb-4">Provider Specs ({filteredProviderSpecs.length})</h3>
                {filteredProviderSpecs.length === 0 ? (
                    <div className="py-8">
                        <EmptyState 
                            title={hasNoSpecs ? "No provider specs" : "No matching specs"}
                            description={hasNoSpecs 
                                ? "No provider specifications are available" 
                                : `No specs match your search query: "${searchQuery}"`
                            }
                            iconsType="llm"
                        />
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
                        {
                            filteredProviderSpecs.map((spec) => (
                                <ProviderSpecCard key={spec.id} spec={spec} />
                            ))
                        }
                    </div>
                )}
            </div>
        </div>
    );
}
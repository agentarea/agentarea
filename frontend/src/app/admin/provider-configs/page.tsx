import { listProviderConfigsWithModelInstances, listProviderSpecsWithModels } from "@/lib/api";
import { Settings, ArrowRight } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import MainContent from "../components/MainContent";

export interface ProviderSpec {
    id: string;
    provider_key: string;
    name: string;
    description: string | null;
    provider_type: string;
    icon_url: string | null;
    is_builtin: boolean;
    models: any[];
}

export interface ModelInstance {
    id: string;
    provider_config_id: string;
    model_spec_id: string;
    name: string;
    description: string | null;
    is_active: boolean;
    is_public: boolean;
    created_at: string;
    updated_at: string;
    provider_name: string | null;
    provider_key: string | null;
    model_name: string | null;
    model_display_name: string | null;
    config_name: string | null;
}

export interface ProviderConfig {
    id: string;
    provider_spec_id: string;
    name: string;
    endpoint_url: string | null;
    is_active: boolean;
    is_public: boolean;
    created_at: string;
    provider_spec_name: string | null;
    provider_spec_key: string | null;
    spec: ProviderSpec;
    model_instances?: ModelInstance[];
}

export default async function ProviderConfigsPage({
    searchParams,
}: {
    searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
    const t = await getTranslations("Models");
    const resolvedSearchParams = await searchParams;

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
                    Error loading data: {
                        specsError?.detail?.[0]?.msg || 
                        configsError?.detail?.[0]?.msg ||
                        'Unknown error occurred'
                    }
                </p>
            </div>
        );
    }

    const providerSpecs = specsResponse.data || [];
    const providerConfigs = (configsResponse.data || []) as any[];

    // Create a map of provider specs for easy lookup
    const specsMap = new Map(providerSpecs.map(spec => [spec.id, spec]));

    // Enhance configs with spec information
    const enhancedConfigs = providerConfigs.map(config => ({
        ...config,
        spec: specsMap.get(config.provider_spec_id)
    }));

    return (
        <ContentBlock 
                header={{
                    breadcrumb: [
                        {label: t("title"), href: "/admin/provider-configs"},
                    ],
                    description: t("description"),
                    controls: (
                        <Link href="/admin/provider-configs/create">
                            <Button className="shrink-0 gap-2 shadow-sm" data-test="new-config-button">
                                <Settings className="mr-2 h-4 w-4" />
                                {t("createButton")}
                            </Button>
                        </Link>
                    )
                }}
        >
            <MainContent 
                resolvedSearchParams={resolvedSearchParams}
                enhancedConfigs={enhancedConfigs as ProviderConfig[]}
                providerSpecs={providerSpecs}
            />

            
        </ContentBlock>
    );
} 
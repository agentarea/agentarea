import { listProviderConfigs, listProviderSpecsWithModels } from "@/lib/api";
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
}

export default async function ProviderConfigsPage({
    searchParams,
}: {
    searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
    const t = await getTranslations("Models");
    const resolvedSearchParams = await searchParams;

    // Fetch both provider specs and configs
    const [specsResponse, configsResponse] = await Promise.all([
        listProviderSpecsWithModels(),
        listProviderConfigs()
    ]);

    if (specsResponse.error || configsResponse.error) {
        return (
            <div className="text-center py-10">
                <p className="text-red-500">Error loading data: {specsResponse.error?.message || configsResponse.error?.message}</p>
            </div>
        );
    }

    const providerSpecs = specsResponse.data || [];
    const providerConfigs = configsResponse.data || [];

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
                    title: t("title"),
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
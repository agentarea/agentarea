import { Input } from "@/components/ui/input";
import { listProviderConfigs, listProviderSpecsWithModels } from "@/lib/api";
import { SearchIcon, Settings, ArrowRight } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { GridAndTableSectionsViews } from "@/components/GridAndTableViews/GridAndTableViews";
import CardContent from "../components/CardContent";
import ModelsList from "../components/ModelsList";
import EmptyState from "@/components/EmptyState/EmptyState";

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
    const commonT = await getTranslations("Common");
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

    // Columns for configured providers
    const configColumns = [
        {
            header: t("table.provider"),
            accessor: "name",
            render: (value: string, row: any) => {
                const spec = row.spec|| row;

                return (
                    <div className="flex items-center gap-3">
                        {spec?.icon_url && (
                            <img 
                                src={spec.icon_url} 
                                alt={`${spec.name} icon`} 
                                className="w-8 h-8 rounded dark:invert"
                            />
                        )}
                        <div>
                            <div className="font-medium">{row.name}</div>
                            <div className="text-xs text-muted-foreground">{spec?.provider_key}</div>
                        </div>
                    </div>
                );
            },
        },
        {
            header: t("table.description"),
            accessor: "description",
            render: (value: string, row: any) => {
                const spec = row.spec || row;
                return (
                    <div className="text-xs text-muted-foreground max-w-xs truncate">
                        {spec.description || 'No description'}
                    </div>
                );
            },

        },
        {
            header: t("table.models"),
            accessor: "models",
            render: (value: string, row: any) => {
                const spec = row.spec|| row;
                return (
                    <ModelsList models={spec.models} />
                );
            },
        },
        {
            header: "",
            accessor: "id",
            render: (value: string, row: any) => {
                return (
                    <Link href={`/admin/provider-configs/create?provider_spec_id=${row.provider_spec_id || row.id}`} 
                        className="flex justify-end small-link opacity-50 hover:opacity-100 transition-all duration-300">
                        {row.spec ? t("editConfiguration") : t("configureProvider")}
                        <ArrowRight className="h-4 w-4" />
                    </Link>
                );
            },
        },
    ];

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

            {/* Configured Providers Section */}
            <div className="content-section">
                <GridAndTableSectionsViews searchParams={resolvedSearchParams}
                        data={[
                            {
                                sectionId: "configured",
                                cardClassName: "border-primary/50 dark:border-accent-foreground",
                                data: enhancedConfigs,
                                emptyState: (
                                    <EmptyState
                                        title={t("emptyState.title")}
                                        description={t("emptyState.description")}
                                        iconsType="llm"
                                        action={{
                                            label: t("createButton"),
                                            href: "/admin/provider-configs/create"
                                        }}
                                    />
                                )
                            },
                            {
                                sectionId: "available",
                                sectioName: t("availableProviders"),
                                data: providerSpecs
                            }
                        ]}
                        columns={configColumns}
                        routeChange="/admin/provider-configs"
                        itemLink={(item: ProviderConfig) => `/admin/provider-configs/create?provider_spec_id=${item.provider_spec_id || item.id}`}
                        cardContent={(item: any) => {
                            return (
                                <CardContent item={item}/>
                            );
                        }}
                        leftComponent={
                            <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                                <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                    <SearchIcon className="h-4 w-4" />
                                </div>
                                <Input 
                                    placeholder={commonT("search")}
                                    className="pl-9 w-full" 
                                />
                            </div>
                        }
                />
            </div>
        </ContentBlock>
    );
} 
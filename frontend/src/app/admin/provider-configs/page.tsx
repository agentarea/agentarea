import { Input } from "@/components/ui/input";
import { listProviderConfigs, listProviderSpecsWithModels } from "@/lib/api";
import { SearchIcon, PlusCircleIcon, Key, Globe, Edit, Settings } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";

interface ProviderSpec {
    id: string;
    provider_key: string;
    name: string;
    description: string | null;
    provider_type: string;
    icon_url: string | null;
    is_builtin: boolean;
    models: any[];
}

interface ProviderConfig {
    id: string;
    provider_spec_id: string;
    name: string;
    endpoint_url: string | null;
    is_active: boolean;
    is_public: boolean;
    created_at: string;
    provider_spec_name: string | null;
    provider_spec_key: string | null;
}

export default async function ProviderConfigsPage({
    searchParams,
}: {
    searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
    const t = await getTranslations("Common");
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
            header: "Provider",
            accessor: "name",
            render: (value: string, row: any) => {
                const spec = row.spec;
                return (
                    <div className="flex items-center gap-3">
                        {spec?.icon_url && (
                            <img 
                                src={spec.icon_url} 
                                alt={`${spec.name} icon`} 
                                className="w-8 h-8 rounded"
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
            header: "Type",
            accessor: "provider_type",
            render: (value: string, row: any) => {
                const spec = row.spec;
                return (
                    <div className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full">
                        {spec?.provider_type}
                    </div>
                );
            },
        },
        {
            header: "Models",
            accessor: "models",
            render: (value: string, row: any) => {
                const spec = row.spec;
                return (
                    <div className="text-xs text-muted-foreground">
                        {spec?.models?.length || 0} models
                    </div>
                );
            },
        },
        {
            header: "Status",
            accessor: "is_active",
            render: (value: boolean, row: any) => {
                return (
                    <div className={`text-xs px-2 py-1 rounded-full ${
                        value 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-red-100 text-red-800'
                    }`}>
                        {value ? 'Active' : 'Inactive'}
                    </div>
                );
            },
        },
        {
            header: "Visibility",
            accessor: "is_public",
            render: (value: boolean, row: any) => {
                return (
                    <div className={`text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
                        value 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-gray-100 text-gray-800'
                    }`}>
                        {value ? <Globe className="h-3 w-3" /> : <Key className="h-3 w-3" />}
                        {value ? 'Public' : 'Private'}
                    </div>
                );
            },
        },
        {
            header: "Actions",
            accessor: "actions",
            render: (value: string, row: any) => {
                return (
                    <div className="flex gap-2">
                        <Link href={`/admin/provider-configs/${row.id}`}>
                            <Button variant="outline" size="sm" className="h-8 w-8 p-0">
                                <Edit className="h-4 w-4" />
                            </Button>
                        </Link>
                    </div>
                );
            },
        },
    ];

    // Columns for available providers
    const specColumns = [
        {
            header: "Provider",
            accessor: "name",
            render: (value: string, row: ProviderSpec) => {
                return (
                    <div className="flex items-center gap-3">
                        {row.icon_url && (
                            <img 
                                src={row.icon_url} 
                                alt={`${row.name} icon`} 
                                className="w-8 h-8 rounded"
                            />
                        )}
                        <div>
                            <div className="font-medium">{row.name}</div>
                            <div className="text-xs text-muted-foreground">{row.provider_key}</div>
                        </div>
                    </div>
                );
            },
        },
        {
            header: "Type",
            accessor: "provider_type",
            render: (value: string, row: ProviderSpec) => {
                return (
                    <div className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full">
                        {row.provider_type}
                    </div>
                );
            },
        },
        {
            header: "Models",
            accessor: "models",
            render: (value: any[], row: ProviderSpec) => {
                return (
                    <div className="text-xs text-muted-foreground">
                        {row.models?.length || 0} models
                    </div>
                );
            },
        },
        {
            header: "Description",
            accessor: "description",
            render: (value: string, row: ProviderSpec) => {
                return (
                    <div className="text-xs text-muted-foreground max-w-xs truncate">
                        {row.description || 'No description'}
                    </div>
                );
            },
        },
        {
            header: "Actions",
            accessor: "actions",
            render: (value: string, row: ProviderSpec) => {
                return (
                    <div className="flex gap-2">
                        <Link href={`/admin/provider-configs/create?provider_spec_id=${row.id}`}>
                            <Button variant="outline" size="sm" className="h-8 px-3">
                                <Settings className="h-4 w-4 mr-1" />
                                Configure
                            </Button>
                        </Link>
                    </div>
                );
            },
        },
    ];

    return (
        <div className="space-y-8">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold">Provider Management</h1>
                    <p className="text-muted-foreground">Manage AI provider configurations and discover available providers</p>
                </div>
                <div className="flex gap-2">
                    <Link href="/admin/providers/create">
                        <Button variant="outline" className="shrink-0 gap-2 shadow-sm">
                            <PlusCircleIcon className="mr-2 h-4 w-4" />
                            Add Provider
                        </Button>
                    </Link>
                    <Link href="/admin/provider-configs/create">
                        <Button className="shrink-0 gap-2 shadow-sm" data-test="new-config-button">
                            <Settings className="mr-2 h-4 w-4" />
                            Add Configuration
                        </Button>
                    </Link>
                </div>
            </div>

            {/* Configured Providers Section */}
            <ContentBlock 
                header={{
                    title: "Configured Providers",
                    description: `${enhancedConfigs.length} provider configurations`,
                }}
            >
                {enhancedConfigs.length > 0 ? (
                    <GridAndTableViews 
                        searchParams={resolvedSearchParams}
                        data={enhancedConfigs}
                        columns={configColumns}
                        routeChange="/admin/provider-configs"
                        cardContent={(item: any) => {
                            const spec = item.spec;
                            return (
                                <div className="flex flex-col gap-2">
                                    <div className="flex items-center gap-3 mb-2">
                                        {spec?.icon_url && (
                                            <img 
                                                src={spec.icon_url} 
                                                alt={`${spec.name} icon`} 
                                                className="w-8 h-8 rounded"
                                            />
                                        )}
                                        <div className="flex-1">
                                            <div className="font-[500] text-[16px] font-montserrat">
                                                {item.name}
                                            </div>
                                            <div className="text-xs text-muted-foreground">{spec?.provider_key}</div>
                                        </div>
                                        <div className="bg-green-100 text-green-800 text-xs px-2 py-1 rounded-full">
                                            Configured
                                        </div>
                                    </div>
                                    <div className="text-[14px] opacity-50 line-clamp-2">
                                        {item.endpoint_url ? `Custom endpoint: ${item.endpoint_url}` : 'Default endpoint'}
                                    </div>
                                    <div className="flex gap-2 text-xs text-muted-foreground">
                                        <span>Type: {spec?.provider_type}</span>
                                        <span>•</span>
                                        <span>Models: {spec?.models?.length || 0}</span>
                                    </div>
                                    <div className="flex gap-2">
                                        <div className={`text-xs px-2 py-1 rounded-full ${
                                            item.is_active 
                                                ? 'bg-green-100 text-green-800' 
                                                : 'bg-red-100 text-red-800'
                                        }`}>
                                            {item.is_active ? 'Active' : 'Inactive'}
                                        </div>
                                        <div className={`text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
                                            item.is_public 
                                                ? 'bg-green-100 text-green-800' 
                                                : 'bg-gray-100 text-gray-800'
                                        }`}>
                                            {item.is_public ? <Globe className="h-3 w-3" /> : <Key className="h-3 w-3" />}
                                            {item.is_public ? 'Public' : 'Private'}
                                        </div>
                                    </div>
                                    <div className="flex gap-2 mt-3">
                                        <Link href={`/admin/provider-configs/${item.id}`}>
                                            <Button variant="outline" size="sm" className="flex-1">
                                                <Edit className="h-4 w-4 mr-2" />
                                                Edit Configuration
                                            </Button>
                                        </Link>
                                    </div>
                                </div>
                            );
                        }}
                        leftComponent={
                            <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                                <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                    <SearchIcon className="h-4 w-4" />
                                </div>
                                <Input 
                                    placeholder="Search configurations..."
                                    className="pl-9 w-full" 
                                />
                            </div>
                        }
                    />
                ) : (
                    <EmptyState
                        title="No configurations yet"
                        description="Create your first provider configuration to get started"
                        iconsType="llm"
                        action={{
                            label: "Add Configuration",
                            href: "/admin/provider-configs/create"
                        }}
                    />
                )}
            </ContentBlock>

            {/* Available Providers Section */}
            <ContentBlock 
                header={{
                    title: "Available Providers",
                    description: `${providerSpecs.length} provider specifications available`,
                }}
            >
                <GridAndTableViews 
                    searchParams={resolvedSearchParams}
                    data={providerSpecs}
                    columns={specColumns}
                    routeChange="/admin/provider-configs"
                    cardContent={(item: ProviderSpec) => {
                        return (
                            <div className="flex flex-col gap-2">
                                <div className="flex items-center gap-3 mb-2">
                                    {item.icon_url && (
                                        <img 
                                            src={item.icon_url} 
                                            alt={`${item.name} icon`} 
                                            className="w-8 h-8 rounded"
                                        />
                                    )}
                                    <div className="flex-1">
                                        <div className="font-[500] text-[16px] font-montserrat">
                                            {item.name}
                                        </div>
                                        <div className="text-xs text-muted-foreground">{item.provider_key}</div>
                                    </div>
                                    <div className="bg-gray-100 text-gray-800 text-xs px-2 py-1 rounded-full">
                                        Available
                                    </div>
                                </div>
                                <div className="text-[14px] opacity-50 line-clamp-2">
                                    {item.description || 'No description'}
                                </div>
                                <div className="flex gap-2 text-xs text-muted-foreground">
                                    <span>Type: {item.provider_type}</span>
                                    <span>•</span>
                                    <span>Models: {item.models?.length || 0}</span>
                                </div>
                                <div className="flex gap-2">
                                    <div className={`text-xs px-2 py-1 rounded-full ${
                                        item.is_builtin 
                                            ? 'bg-green-100 text-green-800' 
                                            : 'bg-gray-100 text-gray-800'
                                    }`}>
                                        {item.is_builtin ? 'Built-in' : 'Custom'}
                                    </div>
                                </div>
                                <div className="flex gap-2 mt-3">
                                    <Link href={`/admin/provider-configs/create?provider_spec_id=${item.id}`}>
                                        <Button variant="outline" size="sm" className="flex-1">
                                            <Settings className="h-4 w-4 mr-2" />
                                            Configure Provider
                                        </Button>
                                    </Link>
                                </div>
                            </div>
                        );
                    }}
                    leftComponent={
                        <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                            <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                <SearchIcon className="h-4 w-4" />
                            </div>
                            <Input 
                                placeholder="Search providers..."
                                className="pl-9 w-full" 
                            />
                        </div>
                    }
                />
            </ContentBlock>
        </div>
    );
} 
import { Input } from "@/components/ui/input";
import { listProviderConfigs } from "@/lib/api";
import { SearchIcon, PlusCircleIcon, Key, Globe, Edit } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";

export default async function ProviderConfigsPage({
    searchParams,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
}) {
    const t = await getTranslations('Common');

    // Fetch provider configs
    const configsResponse = await listProviderConfigs();
    const providerConfigs = configsResponse.data || [];

    const columns = [
        {
            header: "Configuration Name",
            accessor: "name",
            render: (value: string, row: any) => (
                <div className="flex items-center gap-3">
                    <div className="h-8 w-8 bg-blue-100 rounded flex items-center justify-center">
                        <Key className="h-4 w-4 text-blue-600" />
                    </div>
                    <div>
                        <div className="font-semibold text-[14px] md:text-[16px]">{value}</div>
                        <div className="text-xs text-muted-foreground">{row.provider_spec_name}</div>
                    </div>
                </div>
            ),
        },
        {
            header: "Provider",
            accessor: "provider_spec_name",
            render: (value: string, row: any) => (
                <div className="text-[12px] md:text-[14px]">
                    <div className="font-medium">{value}</div>
                    <div className="text-xs text-muted-foreground">{row.provider_spec_key}</div>
                </div>
            ),
        },
        {
            header: "Endpoint",
            accessor: "endpoint_url",
            render: (value: string) => (
                <div className="text-xs text-muted-foreground max-w-xs truncate">
                    {value || 'Default'}
                </div>
            ),
        },
        {
            header: "Visibility",
            accessor: "is_public",
            render: (value: boolean) => (
                <div className={`text-xs px-2 py-1 rounded-full flex items-center gap-1 ${
                    value 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-100 text-gray-800'
                }`}>
                    {value ? <Globe className="h-3 w-3" /> : <Key className="h-3 w-3" />}
                    {value ? 'Public' : 'Private'}
                </div>
            ),
        },
        {
            header: "Status",
            accessor: "is_active",
            render: (value: boolean) => (
                <div className={`text-xs px-2 py-1 rounded-full ${
                    value 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-red-100 text-red-800'
                }`}>
                    {value ? 'Active' : 'Inactive'}
                </div>
            ),
        },
        {
            header: "Created",
            accessor: "created_at",
            render: (value: string) => (
                <div className="text-xs text-muted-foreground">
                    {new Date(value).toLocaleDateString()}
                </div>
            ),
        },
        {
            header: "Actions",
            accessor: "id",
            render: (value: string, row: any) => (
                <div className="flex gap-2">
                    <Link href={`/admin/provider-configs/${value}`} passHref legacyBehavior>
                        <Button variant="outline" size="sm" className="h-8 w-8 p-0">
                            <Edit className="h-4 w-4" />
                        </Button>
                    </Link>
                </div>
            ),
        },
    ];

    return (
        <ContentBlock 
            header={{
                title: "Provider Configurations",
                description: "Manage API configurations for AI providers",
                controls: (
                    <Link href="/admin/provider-configs/create" passHref legacyBehavior>
                        <Button className="shrink-0 gap-2 shadow-sm" data-test="new-config-button">
                            <PlusCircleIcon className="mr-2 h-4 w-4" />
                            Add Configuration
                        </Button>
                    </Link>
                )
            }}
        >
            <GridAndTableViews 
                searchParams={searchParams}
                data={providerConfigs}
                columns={columns}
                emptyState={
                    <EmptyState
                        title="No provider configurations"
                        description="Add a new provider configuration to connect to AI services"
                        iconsType="llm"
                        action={{
                            label: "Add Configuration",
                            href: "/admin/provider-configs/create"
                        }}
                    />
                }
                routeChange="/admin/provider-configs" 
                cardContent={(item: any) => (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-3 mb-2">
                            <div className="h-8 w-8 bg-blue-100 rounded flex items-center justify-center">
                                <Key className="h-4 w-4 text-blue-600" />
                            </div>
                            <div>
                                <div className="font-[500] text-[16px] font-montserrat">{item.name}</div>
                                <div className="text-xs text-muted-foreground">{item.provider_spec_name}</div>
                            </div>
                        </div>
                        <div className="text-[14px] opacity-50 line-clamp-2">
                            {item.endpoint_url ? `Custom endpoint: ${item.endpoint_url}` : 'Default endpoint'}
                        </div>
                        <div className="flex gap-2 text-xs text-muted-foreground">
                            <span>Provider: {item.provider_spec_key}</span>
                            <span>•</span>
                            <span>Created: {new Date(item.created_at).toLocaleDateString()}</span>
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
                            <Link href={`/admin/provider-configs/${item.id}`} passHref legacyBehavior>
                                <Button variant="outline" size="sm" className="flex-1">
                                    <Edit className="h-4 w-4 mr-2" />
                                    Edit
                                </Button>
                            </Link>
                        </div>
                    </div>
                )}
                leftComponent={
                    <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                        <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                            <SearchIcon className="h-4 w-4" />
                        </div>
                        <Input 
                            placeholder={t('search')}
                            className="pl-9 w-full" 
                        />
                    </div>
                }
            />
        </ContentBlock>
    );
} 
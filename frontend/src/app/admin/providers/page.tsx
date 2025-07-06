import { Input } from "@/components/ui/input";
import { listProviderSpecsWithModels } from "@/lib/api";
import { SearchIcon, PlusCircleIcon } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";

export default async function ProviderSpecsPage({
    searchParams,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
}) {
    const t = await getTranslations('Common');

    // Fetch provider specs with models
    const providersResponse = await listProviderSpecsWithModels();
    const providerSpecs = providersResponse.data || [];

    const columns = [
        {
            header: "Provider",
            accessor: "name",
            render: (value: string, row: any) => (
                <div className="flex items-center gap-3">
                    {row.icon_url && (
                        <img 
                            src={row.icon_url} 
                            alt={`${value} icon`} 
                            className="w-6 h-6 rounded"
                        />
                    )}
                    <div>
                        <div className="font-semibold text-[14px] md:text-[16px]">{value}</div>
                        <div className="text-xs text-muted-foreground">{row.provider_key}</div>
                    </div>
                </div>
            ),
        },
        {
            header: "Description",
            accessor: "description",
            cellClassName: "text-[12px] md:text-[14px]",
            render: (value: string) => (
                <div className="line-clamp-3 md:line-clamp-none">{value || 'No description'}</div>
            ),
        },
        {
            header: "Type",
            accessor: "provider_type",
            render: (value: string) => (
                <div className="text-xs px-2 py-1 rounded-full bg-blue-100 text-blue-800">
                    {value}
                </div>
            ),
        },
        {
            header: "Models",
            accessor: "models",
            render: (models: any[]) => (
                <div className="text-xs text-muted-foreground">
                    {models?.length || 0} models
                </div>
            ),
        },
        {
            header: "Status",
            accessor: "is_builtin",
            render: (value: boolean) => (
                <div className={`text-xs px-2 py-1 rounded-full ${
                    value 
                        ? 'bg-green-100 text-green-800' 
                        : 'bg-gray-100 text-gray-800'
                }`}>
                    {value ? 'Built-in' : 'Custom'}
                </div>
            ),
        },
    ];

    return (
        <ContentBlock 
            header={{
                title: "Provider Specifications",
                description: "Manage AI provider specifications and their available models",
                controls: (
                    <Link href="/admin/providers/create" passHref legacyBehavior>
                        <Button className="shrink-0 gap-2 shadow-sm" data-test="new-provider-button">
                            <PlusCircleIcon className="mr-2 h-4 w-4" />
                            Add Provider
                        </Button>
                    </Link>
                )
            }}
        >
            <GridAndTableViews 
                searchParams={searchParams}
                data={providerSpecs}
                columns={columns}
                emptyState={
                    <EmptyState
                        title="No provider specifications"
                        description="Add a new provider specification to get started"
                        iconsType="llm"
                        action={{
                            label: "Add Provider",
                            href: "/admin/providers/create"
                        }}
                    />
                }
                routeChange="/admin/providers" 
                cardContent={(item: any) => (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-3 mb-2">
                            {item.icon_url && (
                                <img 
                                    src={item.icon_url} 
                                    alt={`${item.name} icon`} 
                                    className="w-8 h-8 rounded"
                                />
                            )}
                            <div>
                                <div className="font-[500] text-[16px] font-montserrat">{item.name}</div>
                                <div className="text-xs text-muted-foreground">{item.provider_key}</div>
                            </div>
                        </div>
                        <div className="text-[14px] opacity-50 line-clamp-2">{item.description || 'No description'}</div>
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
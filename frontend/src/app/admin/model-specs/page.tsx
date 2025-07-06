import { Input } from "@/components/ui/input";
import { listModelSpecs } from "@/lib/api";
import { SearchIcon, PlusCircleIcon, Cpu, Brain } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";

export default async function ModelSpecsPage({
    searchParams,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
}) {
    const t = await getTranslations('Common');

    // Fetch model specs
    const modelSpecsResponse = await listModelSpecs();
    const modelSpecs = modelSpecsResponse.data || [];

    const columns = [
        {
            header: "Model",
            accessor: "display_name",
            render: (value: string, row: any) => (
                <div className="flex items-center gap-3">
                    <div className="h-8 w-8 bg-purple-100 rounded flex items-center justify-center">
                        <Brain className="h-4 w-4 text-purple-600" />
                    </div>
                    <div>
                        <div className="font-semibold text-[14px] md:text-[16px]">{value}</div>
                        <div className="text-xs text-muted-foreground">{row.model_name}</div>
                    </div>
                </div>
            ),
        },
        {
            header: "Provider",
            accessor: "provider_name",
            render: (value: string, row: any) => (
                <div className="text-[12px] md:text-[14px]">
                    <div className="font-medium">{value}</div>
                    <div className="text-xs text-muted-foreground">{row.provider_key}</div>
                </div>
            ),
        },
        {
            header: "Description",
            accessor: "description",
            cellClassName: "text-[12px] md:text-[14px]",
            render: (value: string) => (
                <div className="line-clamp-2 max-w-xs">{value || 'No description'}</div>
            ),
        },
        {
            header: "Context Window",
            accessor: "context_window",
            render: (value: number) => (
                <div className="text-xs text-muted-foreground flex items-center gap-1">
                    <Cpu className="h-3 w-3" />
                    {value?.toLocaleString() || 'N/A'}
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
    ];

    return (
        <ContentBlock 
            header={{
                title: "Model Specifications",
                description: "Manage AI model specifications and their capabilities",
                controls: (
                    <Link href="/admin/model-specs/create" passHref legacyBehavior>
                        <Button className="shrink-0 gap-2 shadow-sm" data-test="new-model-spec-button">
                            <PlusCircleIcon className="mr-2 h-4 w-4" />
                            Add Model Spec
                        </Button>
                    </Link>
                )
            }}
        >
            <GridAndTableViews 
                searchParams={searchParams}
                data={modelSpecs}
                columns={columns}
                emptyState={
                    <EmptyState
                        title="No model specifications"
                        description="Add a new model specification to define available AI models"
                        iconsType="llm"
                        action={{
                            label: "Add Model Spec",
                            href: "/admin/model-specs/create"
                        }}
                    />
                }
                routeChange="/admin/model-specs" 
                cardContent={(item: any) => (
                    <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-3 mb-2">
                            <div className="h-8 w-8 bg-purple-100 rounded flex items-center justify-center">
                                <Brain className="h-4 w-4 text-purple-600" />
                            </div>
                            <div>
                                <div className="font-[500] text-[16px] font-montserrat">{item.display_name}</div>
                                <div className="text-xs text-muted-foreground">{item.model_name}</div>
                            </div>
                        </div>
                        <div className="text-[14px] opacity-50 line-clamp-2">{item.description || 'No description'}</div>
                        <div className="flex gap-2 text-xs text-muted-foreground">
                            <span>Provider: {item.provider_name}</span>
                            <span>•</span>
                            <span>Context: {item.context_window?.toLocaleString() || 'N/A'}</span>
                        </div>
                        <div className="flex gap-2">
                            <div className={`text-xs px-2 py-1 rounded-full ${
                                item.is_active 
                                    ? 'bg-green-100 text-green-800' 
                                    : 'bg-red-100 text-red-800'
                            }`}>
                                {item.is_active ? 'Active' : 'Inactive'}
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
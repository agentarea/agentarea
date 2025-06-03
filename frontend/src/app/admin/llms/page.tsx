import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { listLLMModelInstances } from "@/lib/api";
import { LayoutDashboardIcon, SearchIcon, TablePropertiesIcon, PlusCircleIcon } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { redirect } from 'next/navigation';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import GridView from "./_components/GridView";
import TableView from "./_components/TableView";
import EmptyState from "@/components/EmptyState/EmptyState";

// Server component that handles the tab rendering
export default async function AddLLMModelPage({
    searchParams,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
}) {
    const t = await getTranslations('LlmBrowsePage');
    const commonT = await getTranslations('Common');

    // Get tab from URL query params
    const tab = ( await searchParams).tab;
    const activeTab = (typeof tab === 'string' && (tab === 'grid' || tab === 'table')) 
        ? tab 
        : 'grid';

    // If no valid tab in URL, redirect to default
    if (!tab || (typeof tab === 'string' && !['grid', 'table'].includes(tab))) {
        redirect('/admin/llms?tab=grid');
    }

    // const llmModels = (await listLLMModels()).data || [];
    const llmModelInstances = (await listLLMModelInstances()).data || [];

    return (
        <ContentBlock 
            header={{
                title: t('title'),
                controls: (
                    <Link href="/admin/llms/create" passHref legacyBehavior>
                        <Button className="shrink-0 gap-2 shadow-sm" data-test="new-llm-button">
                            <PlusCircleIcon className="mr-2 h-4 w-4" />
                            {t('addNewLlm')}
                        </Button>
                    </Link>
                )
            }}
            
        >
            <TabsWithNavigation activeTab={activeTab}>
                <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
                   <div className="flex flex-row items-center gap-[10px] flex-1">
                        <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                            <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                <SearchIcon className="h-4 w-4" />
                            </div>
                            <Input 
                                placeholder={commonT('search')}
                                className="pl-9 w-full" 
                            />
                        </div>
                    </div>

                    <div>
                        <TabsList>
                            <TabsTrigger value="grid" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]">
                                <LayoutDashboardIcon className="w-5 h-5" /> 
                                <span className="hidden sm:block">{commonT('grid')}</span>
                            </TabsTrigger>
                            <TabsTrigger value="table" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]">
                                <TablePropertiesIcon className="w-5 h-5" /> 
                                <span className="hidden sm:block">{commonT('table')}</span>
                            </TabsTrigger>
                        </TabsList>
                    </div>
                </div>

                {!llmModelInstances.length ? (
                    <EmptyState
                        title={t('noLlmInstances')}
                        description={t('setUpNewLlm')}
                        iconsType="llm"
                        action={{
                            label: t('addNewLlm'),
                            href: "/admin/llms/create"
                        }}
                    />
                    ) : (
                        <>
                            <TabsContent value="grid">
                                <GridView instances={llmModelInstances} />
                            </TabsContent>
                            <TabsContent value="table">
                                <TableView instances={llmModelInstances} />
                            </TabsContent>
                        </>
                    )
                }
            </TabsWithNavigation>
        </ContentBlock>
    )
}

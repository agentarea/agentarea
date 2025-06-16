import { Input } from "@/components/ui/input";
import { listLLMModelInstances } from "@/lib/api";
import { SearchIcon, PlusCircleIcon } from "lucide-react";
import { getTranslations } from 'next-intl/server';
import { Button } from "@/components/ui/button";
import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";


// Server component that handles the tab rendering
export default async function AddLLMModelPage({
    searchParams,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
}) {
    const t = await getTranslations('LlmBrowsePage');
    const commonT = await getTranslations('Common');

    // const llmModels = (await listLLMModels()).data || [];
    const llmModelInstances = (await listLLMModelInstances()).data || [];

    const columns = [
        {
          header: "Name",
          accessor: "name",
          render: (value: string) => (
            <div className="font-semibold font-montserrat text-[14px] md:text-[16px] flex flex-col md:flex-row md:items-center gap-[10px] md:gap-[15px]">
              {value}
            </div>
          ),
        },
        {
          header: "Description",
          accessor: "description",
          cellClassName: "text-[12px] md:text-[14px]",
          render: (value: string) => (
            <div className="line-clamp-3 md:line-clamp-none">{value}</div>
          ),
        },
        {
          header: "Status",
          accessor: "status",
          render: (value: string) => <div className="text-xs text-muted-foreground">{value}</div>,
        },
      ];

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
            <GridAndTableViews 
                searchParams={searchParams}
                data={llmModelInstances}
                columns={columns}
                emptyState={
                    <EmptyState
                        title={t('noLlmInstances')}
                        description={t('setUpNewLlm')}
                        iconsType="llm"
                        action={{
                            label: t('addNewLlm'),
                            href: "/admin/llms/create"
                        }}
                    />
                }
                routeChange="/admin/llms" 
                cardContent={(item: any) => (
                    <div className="flex flex-col gap-2">
                        <div className="font-[500] text-[16px] font-montserrat">{item.name}</div>
                        <div className="text-[14px] opacity-50 line-clamp-2 pt-[10px]">{item.description}</div>
                        <div className="text-xs text-muted-foreground">Status: {item.status}</div>
                    </div>
                )}
                leftComponent={
                    <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                        <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                            <SearchIcon className="h-4 w-4" />
                        </div>
                        <Input 
                            placeholder={commonT('search')}
                            className="pl-9 w-full" 
                        />
                    </div>
                }
            />
        </ContentBlock>
    )
}
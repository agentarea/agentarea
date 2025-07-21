import { TabsWithNavigation } from "./components/TabsWithNavigation";
import { TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LayoutDashboardIcon, TablePropertiesIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState/EmptyState";
import Table from "@/components/Table/Table";

export default function GridAndTableViews({
    searchParams,
    emptyState,
    leftComponent,
    routeChange,
    data,
    columns,
    cardContent,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
    isEmpty?: boolean;
    emptyState?: React.ReactNode;
    leftComponent?: React.ReactNode;
    routeChange: string;
    data: any[];
    columns: any[];
    cardContent: (item: any) => React.ReactNode;
}) {

    const t = useTranslations("Common");

    const tab = searchParams?.tab;
    const activeTab = (typeof tab === 'string' && (tab === 'grid' || tab === 'table')) 
        ? tab 
        : 'grid';

    return (
        <TabsWithNavigation activeTab={activeTab} routeChange={routeChange}>
            <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
                <div className="flex flex-row items-center gap-[10px] flex-1">
                    {leftComponent}
                </div>

                <div>
                    <TabsList>
                        <TabsTrigger value="grid" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]">
                            <LayoutDashboardIcon className="w-5 h-5" /> 
                            <span className="hidden sm:block">{t('grid')}</span>
                        </TabsTrigger>
                        <TabsTrigger value="table" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]">
                            <TablePropertiesIcon className="w-5 h-5" /> 
                            <span className="hidden sm:block">{t('table')}</span>
                        </TabsTrigger>
                    </TabsList>
                </div>
            </div>

            {!data.length ? (
                emptyState || (<EmptyState
                    title={t('emptyState.title')}
                    description={t('emptyState.description')}
                    iconsType="agent"
                />)
                ) : (
                    <>
                        <TabsContent value="grid">
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-[12px]">
                                {data.map((item) => (
                                    <div key={item.id} className="card card-shadow group">
                                        {cardContent(item)}
                                    </div>
                                ))}
                            </div>
                        </TabsContent>
                        <TabsContent value="table">
                            <Table data={data} columns={columns} />
                        </TabsContent>
                    </>
                )
            }
        </TabsWithNavigation>
    );
}
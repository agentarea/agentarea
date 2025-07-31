"use client";
import { useTranslations } from "next-intl";
import { TabsWithNavigation } from "./TabsWithNavigation";
import { TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LayoutDashboardIcon, TablePropertiesIcon } from "lucide-react";

export default function TabsView({
    searchParams,
    leftComponent,
    routeChange,
    children,
}: {
    searchParams: { [key: string]: string | string[] | undefined }
    emptyState?: React.ReactNode;
    leftComponent?: React.ReactNode;
    routeChange: string;
    children: React.ReactNode;
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

            {children}
        </TabsWithNavigation>
    );
}

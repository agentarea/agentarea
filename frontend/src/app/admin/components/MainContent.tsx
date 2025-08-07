"use client";
import { GridAndTableSectionsViews } from "@/components/GridAndTableViews/GridAndTableViews";
import CardContent from "./CardContent";
import { SearchIcon, AlertCircle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTranslations } from "next-intl";
import { ProviderSpec, ProviderConfig } from "../provider-configs/page";
import ModelsList from "./ModelsList";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useEffect, useCallback, useMemo } from "react";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { LoadingSpinner } from "@/components/LoadingSpinner";

import EmptyState from "@/components/EmptyState/EmptyState";
import { useSearchWithDebounce, useTabState, useFilteredData } from "./hooks";

export default function MainContent({
    resolvedSearchParams,
    enhancedConfigs,
    providerSpecs,
}: {
    resolvedSearchParams: { [key: string]: string | string[] | undefined };
    enhancedConfigs: ProviderConfig[];
    providerSpecs: ProviderSpec[];
}) {
    const t = useTranslations("Models");
    const commonT = useTranslations("Common");
    const router = useRouter();
    const searchParams = useSearchParams();
    const pathname = usePathname();
    
    const urlTab = searchParams.get("tab");
    const initialSearchQuery = searchParams.get("search") || "";
    
    // Используем кастомные хуки
    const {
        query: searchQuery,
        debouncedQuery,
        isSearching,
        updateQuery,
        forceUpdate
    } = useSearchWithDebounce(initialSearchQuery);

    const {
        currentTab,
        isTabLoaded,
        updateTab
    } = useTabState(pathname, urlTab);

    // Обновляем URL при изменении поиска
    useEffect(() => {
        const params = new URLSearchParams(searchParams.toString());
        
        if (debouncedQuery.trim()) {
            params.set("search", debouncedQuery);
        } else {
            params.delete("search");
        }
        
        // Сохраняем параметр таба
        if (urlTab) {
            params.set("tab", urlTab);
        }
        
        const newUrl = params.toString() ? `?${params.toString()}` : "";
        router.replace(`/admin/provider-configs${newUrl}`, { scroll: false });
    }, [debouncedQuery, router, searchParams, urlTab]);

    // Сохраняем таб в куки при изменении
    useEffect(() => {
        if (urlTab) {
            updateTab(urlTab);
        }
    }, [urlTab, updateTab]);

    // Обработчики поиска
    const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        updateQuery(e.target.value);
    }, [updateQuery]);

    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            forceUpdate();
        }
    }, [forceUpdate]);

    // Фильтрация данных с использованием кастомного хука
    const filterData = useCallback((data: any[]) => {
        if (!debouncedQuery.trim()) return data;
        
        const query = debouncedQuery.toLowerCase();
        return data.filter(item => {
            const spec = item.spec || item;
            return (
                item.name?.toLowerCase().includes(query) ||
                spec?.name?.toLowerCase().includes(query) ||
                spec?.provider_key?.toLowerCase().includes(query) ||
                spec?.description?.toLowerCase().includes(query)
            );
        });
    }, [debouncedQuery]);

    const filteredConfigs = useMemo(() => filterData(enhancedConfigs), [filterData, enhancedConfigs]);
    const filteredSpecs = useMemo(() => filterData(providerSpecs), [filterData, providerSpecs]);

    // Колонки для настроенных провайдеров
    const configColumns = useMemo(() => [
        {
            header: t("table.provider"),
            accessor: "name",
            render: (value: string, row: any) => {
                const spec = row.spec || row;

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
                const spec = row.spec || row;
                // For provider configs, show model instances instead of all available models
                if (row.model_instances !== undefined) {
                    // This is a provider config
                    const modelInstances = row.model_instances || [];
                    if (modelInstances.length === 0) {
                        return (
                            <Badge variant="yellow" className="w-fit">
                                <AlertCircle className="h-3 w-3 mr-1" />
                                {t("noInstancesConfigured")}
                            </Badge>
                        );
                    }
                    
                    return (
                        <div className="space-y-1">
                            {modelInstances.slice(0, 3).map((instance: any) => (
                                <div key={instance.id} className="flex items-center gap-2 text-xs">
                                    <div className="w-2 h-2 bg-green-500 rounded-full"></div>
                                    <span className="font-medium">{instance.name}</span>
                                    <span className="text-muted-foreground">({instance.model_display_name || instance.model_name})</span>
                                </div>
                            ))}
                            {modelInstances.length > 3 && (
                                <div className="text-xs text-muted-foreground">
                                    +{modelInstances.length - 3} more
                                </div>
                            )}
                        </div>
                    );
                } else {
                    // This is a provider spec, show all available models
                    return (
                        <ModelsList models={spec.models} />
                    );
                }
            },
        },
        {
            header: "",
            accessor: "id",
            render: (value: string, row: any) => {
                // Если это ProviderConfig (есть spec), то редактируем конфигурацию
                if (row.spec) {
                    return (
                        <Link href={`/admin/provider-configs/create?provider_spec_id=${row.id}&isEdit=true`} 
                            className="flex justify-end small-link opacity-50 hover:opacity-100 transition-all duration-300">
                            {t("editConfiguration")}
                            <ArrowRight className="h-4 w-4" />
                        </Link>
                    );
                } else {
                    // Если это ProviderSpec, то создаем новую конфигурацию
                    return (
                        <Link href={`/admin/provider-configs/create?provider_spec_id=${row.id}`} 
                            className="flex justify-end small-link opacity-50 hover:opacity-100 transition-all duration-300">
                            {t("configureProvider")}
                            <ArrowRight className="h-4 w-4" />
                        </Link>
                    );
                }
            },
        },
    ], [t]);

    // Не рендерим до загрузки таба для предотвращения мерцания
    if (!isTabLoaded && !urlTab) {
        return (
            <div className="content-section">
                <div className="flex items-center justify-center h-32">
                    <LoadingSpinner />
                </div>
            </div>
        );
    }

    return (
        <div className="content-section">
            <GridAndTableSectionsViews 
                searchParams={{
                    ...Object.fromEntries(searchParams.entries()),
                    tab: currentTab
                }}
                data={[
                    {
                        sectionId: "configured",
                        itemLink: ((item) => `/admin/provider-configs/create?provider_spec_id=${item.id}&isEdit=true`),
                        cardClassName: "border-primary/50 dark:border-accent-foreground",
                        data: filteredConfigs,
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
                        itemLink: ((item) => `/admin/provider-configs/create?provider_spec_id=${item.id}`),
                        sectionId: "available",
                        sectioName: t("availableProviders"),
                        data: filteredSpecs
                    }
                ]}
                columns={configColumns}
                routeChange="/admin/provider-configs"
                cardContent={(item: any) => {
                    return (
                        <CardContent item={item}/>
                    );
                }}
                leftComponent={
                    <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                        <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                            {isSearching ? (
                                <LoadingSpinner size="sm" text="" />
                            ) : (
                                <SearchIcon className="h-4 w-4" />
                            )}
                        </div>
                        <Input 
                            placeholder={commonT("search")}
                            className="pl-9 w-full" 
                            value={searchQuery}
                            onChange={handleSearchChange}
                            onKeyDown={handleKeyDown}
                        />
                    </div>
                }
            />
        </div>
    );
}
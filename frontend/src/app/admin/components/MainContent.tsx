"use client";
import { GridAndTableSectionsViews } from "@/components/GridAndTableViews/GridAndTableViews";
import CardContent from "./CardContent";
import { SearchIcon } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useTranslations } from "next-intl";
import { ProviderSpec, ProviderConfig } from "../provider-configs/page";
import ModelsList from "./ModelsList";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import EmptyState from "@/components/EmptyState/EmptyState";


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
    
    const [searchQuery, setSearchQuery] = useState(searchParams.get("search") || "");
    const [debouncedSearchQuery, setDebouncedSearchQuery] = useState(searchQuery);
    const [isSearching, setIsSearching] = useState(false);

    // Debounce effect - wait 500ms after user stops typing
    useEffect(() => {
        setIsSearching(true);
        const timer = setTimeout(() => {
            setDebouncedSearchQuery(searchQuery);
            setIsSearching(false);
        }, 1000);

        return () => clearTimeout(timer);
    }, [searchQuery]);

    // Update URL when debounced search changes
    useEffect(() => {
        const params = new URLSearchParams(searchParams.toString());
        
        if (debouncedSearchQuery.trim()) {
            params.set("search", debouncedSearchQuery);
        } else {
            params.delete("search");
        }
        
        const newUrl = params.toString() ? `?${params.toString()}` : "";
        router.replace(`/admin/provider-configs${newUrl}`, { scroll: false });
    }, [debouncedSearchQuery, router, searchParams]);

    // Handle search input change
    const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        setSearchQuery(e.target.value);
    }, []);

    // Handle Enter key press
    const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            setIsSearching(true);
            setDebouncedSearchQuery(searchQuery);
            setIsSearching(false);
        }
    }, [searchQuery]);

    // Filter data based on search query
    const filterData = useCallback((data: any[]) => {
        if (!debouncedSearchQuery.trim()) return data;
        
        const query = debouncedSearchQuery.toLowerCase();
        return data.filter(item => {
            const spec = item.spec || item;
            return (
                item.name?.toLowerCase().includes(query) ||
                spec?.name?.toLowerCase().includes(query) ||
                spec?.provider_key?.toLowerCase().includes(query) ||
                spec?.description?.toLowerCase().includes(query)
            );
        });
    }, [debouncedSearchQuery]);

    const filteredConfigs = filterData(enhancedConfigs);
    const filteredSpecs = filterData(providerSpecs);

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
        <div className="content-section">
            <GridAndTableSectionsViews searchParams={resolvedSearchParams}
                    data={[
                        {
                            sectionId: "configured",
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
                            sectionId: "available",
                            sectioName: t("availableProviders"),
                            data: filteredSpecs
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
                                {isSearching ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
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
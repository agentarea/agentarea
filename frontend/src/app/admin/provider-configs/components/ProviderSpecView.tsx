'use client';

import { ProviderSpec } from "./types";
import EmptyState from "@/components/EmptyState";
import { ProviderSpecCard } from "./ProviderItem";
import Table from "@/components/Table/Table";
import { useRouter } from "next/navigation";
import ModelsList from "./ModelsList";

interface ProviderSpecViewProps {
    specs: ProviderSpec[];
    searchQuery: string;
    viewMode: string;
    hasNoData: boolean;
}

export default function ProviderSpecView({ 
    specs, 
    searchQuery, 
    viewMode,
    hasNoData 
}: ProviderSpecViewProps) {
    const router = useRouter();
    
    // Define table columns for specs
    const specColumns = [
        {
            accessor: "name",
            header: "Name",
            render: (value: string, item: any) => (
                <div className="flex items-center gap-2">
                    {item.icon_url && (
                        <img 
                            src={item.icon_url} 
                            alt={`${value} icon`} 
                            className="w-5 h-5 rounded dark:invert flex-shrink-0"
                        />
                    )}
                    <span className="truncate">{value}</span>
                </div>
            ),
        },
        {
            accessor: "description",
            header: "Description",
            render: (value: string) => (
                <span className="block truncate max-w-[300px]" title={value}>
                    {value || '-'}
                </span>
            ),
        },
        {
            accessor: "models",
            header: "Models",
            render: (value: any[]) => (
                <ModelsList models={value || []} />
            ),
        },
    ];

    // Empty state handling
    if (specs.length === 0) {
        return (
            <div className="py-1">
                <EmptyState 
                    title={hasNoData ? "No provider specs" : "No matching specs"}
                    description={hasNoData 
                        ? "No provider specifications are available" 
                        : `No specs match your search query: "${searchQuery}"`
                    }
                    iconsType="llm"
                />
            </div>
        );
    }

    // Render table view
    if (viewMode === "table") {
        return (
            <Table 
                data={specs} 
                columns={specColumns}
                onRowClick={(spec) => {
                    router.push(`/admin/provider-configs/create?provider_spec_id=${spec.id}`);
                }}
            />
        );
    }

    // Render grid view (default)
    return (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-2">
            {specs.map((spec) => (
                <ProviderSpecCard key={spec.id} spec={spec} />
            ))}
        </div>
    );
}


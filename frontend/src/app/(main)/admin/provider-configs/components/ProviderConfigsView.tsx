"use client";

import { useRouter } from "next/navigation";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import ModelsList from "./ModelsList";
import { ProviderConfigCard } from "./ProviderItem";
import { ProviderConfig } from "./types";

interface ProviderConfigsViewProps {
  configs: ProviderConfig[];
  searchQuery: string;
  viewMode: string;
  hasNoData: boolean;
}

export default function ProviderConfigsView({
  configs,
  searchQuery,
  viewMode,
  hasNoData,
}: ProviderConfigsViewProps) {
  const router = useRouter();

  // Define table columns for configs
  const configColumns = [
    {
      accessor: "name",
      header: "Name",
      render: (value: string, item: any) => (
        <div className="flex items-center gap-2">
          {item.spec?.icon_url && (
            <img
              src={item.spec.icon_url}
              alt={`${item.spec.name} icon`}
              className="h-5 w-5 flex-shrink-0 rounded dark:invert"
            />
          )}
          <span className="truncate">{value}</span>
        </div>
      ),
    },
    {
      accessor: "provider_spec_name",
      header: "Provider",
    },
    {
      accessor: "model_instances",
      header: "Models",
      render: (value: any[]) => <ModelsList models={value || []} />,
    },
  ];

  // Empty state handling
  if (configs.length === 0) {
    return (
      <div className="py-1">
        <EmptyState
          title={hasNoData ? "No provider configs" : "No matching configs"}
          description={
            hasNoData
              ? "No provider configurations are available"
              : `No configs match your search query: "${searchQuery}"`
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
        data={configs}
        columns={configColumns}
        onRowClick={(config) => {
          router.push(
            `/admin/provider-configs/create?provider_spec_id=${config.id}&isEdit=true`
          );
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {configs.map((config) => (
        <ProviderConfigCard key={config.id} config={config} />
      ))}
    </div>
  );
}

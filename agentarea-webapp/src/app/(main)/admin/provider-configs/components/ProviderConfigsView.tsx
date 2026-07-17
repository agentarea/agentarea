"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import ModelsList from "./ModelsList";
import { ProviderConfigCard } from "./ProviderItem";
import { ModelInstance, ProviderConfig } from "./types";

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
  const t = useTranslations("Models.table");
  const router = useRouter();

  // Define table columns for configs
  const configColumns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string, item: ProviderConfig) => (
        <div className="flex items-center gap-2">
          {item.spec?.icon_url && (
            <Image
              src={item.spec.icon_url}
              alt={`${item.spec.name} icon`}
              width={20}
              height={20}
              className="h-5 w-5 flex-shrink-0 rounded dark:invert"
            />
          )}
          <span className="truncate">{value}</span>
        </div>
      ),
    },
    {
      accessor: "provider_spec_name",
      header: t("provider"),
    },
    {
      accessor: "model_instances",
      header: t("models"),
      render: (value: ModelInstance[]) => <ModelsList models={value || []} />,
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
            `/admin/provider-configs/edit/${config.id}`
          );
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className={CARD_GRID_DENSE}>
      {configs.map((config) => (
        <ProviderConfigCard key={config.id} config={config} />
      ))}
    </div>
  );
}

"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import ModelsList from "./ModelsList";
import { ProviderSpecCard } from "./ProviderItem";
import { ProviderSpec } from "./types";

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
  hasNoData,
}: ProviderSpecViewProps) {
  const t = useTranslations("Models.table");
  const router = useRouter();

  // Define table columns for specs
  const specColumns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string, item: any) => (
        <div className="flex items-center gap-2">
          {item.icon_url && (
            <Image
              src={item.icon_url}
              alt={`${value} icon`}
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
      accessor: "description",
      header: t("description"),
      render: (value: string) => (
        <span className="block max-w-[300px] truncate" title={value}>
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "models",
      header: t("models"),
      render: (value: any[]) => <ModelsList models={value || []} />,
    },
  ];

  // Empty state handling
  if (specs.length === 0) {
    return (
      <div className="py-1">
        <EmptyState
          title={hasNoData ? "No provider specs" : "No matching specs"}
          description={
            hasNoData
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
          router.push(
            `/admin/provider-configs/create/${spec.id}`
          );
        }}
      />
    );
  }

  // Render grid view (default)
  return (
    <div className={CARD_GRID_DENSE}>
      {specs.map((spec) => (
        <ProviderSpecCard key={spec.id} spec={spec} />
      ))}
    </div>
  );
}

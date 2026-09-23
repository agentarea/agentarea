"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import Table from "@/components/Table/Table";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import ModelsList, { type ModelEntry } from "./ModelsList";
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
      render: (value: string, item: ProviderSpec) => (
        <div className="flex items-center gap-2">
          {item.icon_url && (
            <span className="avatar-plate grid h-6 w-6 flex-shrink-0 place-items-center rounded-[6px]">
              <Image
                src={item.icon_url}
                alt={`${value} icon`}
                width={20}
                height={20}
                className="h-[16px] w-[16px] object-contain"
              />
            </span>
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
      render: (value: unknown) => <ModelsList models={(value as ModelEntry[]) || []} />,
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
          // Specs come from the registry, so there is nothing to create here --
          // the only useful move on an empty result is dropping the filter.
          action={
            hasNoData ? undefined : { label: "Clear search", href: "/admin/provider-configs" }
          }
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

"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import type { ProviderSpecWithModelsResponse } from "@/api/client/types.gen";
import Table from "@/components/Table/Table";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import { ProviderSpecCard } from "./ProviderItem";

interface ProviderSpecsViewProps {
  specs: ProviderSpecWithModelsResponse[];
  viewMode: string;
}

/**
 * The Available tab's catalog, rendered the way ProviderConfigsView renders
 * the Connected tab: the same card grid and card component, or a table.
 * A catalog entry leads to connecting it, as a config card leads to its edit
 * page; the create page itself tells a member they need an admin.
 */
export default function ProviderSpecsView({
  specs,
  viewMode,
}: ProviderSpecsViewProps) {
  const tProviders = useTranslations("ProvidersPage");

  // Same cell styles as the Connected table and the other lists: logo on a
  // plate, medium-weight name over an 11px key, a one-line description. Type
  // and built-in status are left out: in the registry the type is the key
  // again, and every catalog entry is built in.
  const columns = [
    {
      header: tProviders("table.provider"),
      accessor: "name",
      render: (value: string, row: ProviderSpecWithModelsResponse) => (
        <div className="flex min-w-0 items-center gap-2">
          {row.icon_url && (
            <span className="avatar-plate grid h-6 w-6 flex-shrink-0 place-items-center rounded-[6px]">
              <Image
                src={row.icon_url}
                alt=""
                aria-hidden="true"
                width={20}
                height={20}
                className="h-[16px] w-[16px] object-contain"
              />
            </span>
          )}
          <div className="min-w-0">
            <div className="truncate font-medium">{value}</div>
            <div className="truncate text-[11px] text-muted-foreground">
              {row.provider_key}
            </div>
          </div>
        </div>
      ),
    },
    {
      header: tProviders("table.description"),
      accessor: "description",
      // w-full + max-w-0 lets the description take the spare width and
      // truncate inside it instead of stretching the table.
      cellClassName: "w-full max-w-0",
      render: (value: string) => (
        <div className="table-description truncate" title={value || undefined}>
          {value || "—"}
        </div>
      ),
    },
    {
      header: tProviders("table.models"),
      accessor: "models",
      render: (models: ProviderSpecWithModelsResponse["models"]) => (
        <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
          {tProviders("table.modelCount", { count: models?.length ?? 0 })}
        </span>
      ),
    },
  ];

  if (viewMode === "table") {
    return (
      <Table
        data={specs}
        columns={columns}
        rowHref={(spec) => `/models/create/${spec.id}`}
      />
    );
  }

  return (
    <div className={CARD_GRID_DENSE}>
      {specs.map((spec) => (
        <ProviderSpecCard key={spec.id} spec={spec} />
      ))}
    </div>
  );
}

"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { CARD_GRID_DENSE } from "@/lib/collectionGrids";
import ModelsList from "./ModelsList";
import { PlatformProviderConfigCard } from "./ProviderItem";
import { ModelInstance, ProviderConfig } from "./types";

interface PlatformProviderConfigsViewProps {
  configs: ProviderConfig[];
  viewMode: string;
}

// Platform-supplied configs (config.managed_by === "platform"): read-only,
// so unlike ProviderConfigsView there's no onRowClick / no edit link -- see
// PlatformProviderConfigCard for why the grid card skips LinkedCard too.
export default function PlatformProviderConfigsView({
  configs,
  viewMode,
}: PlatformProviderConfigsViewProps) {
  const t = useTranslations("Models.table");
  const badgeLabel = useTranslations("Models")("platformManagedBadge");

  const configColumns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string, item: ProviderConfig) => (
        <div className="flex items-center gap-2">
          {item.spec?.icon_url && (
            <span className="avatar-plate grid h-6 w-6 flex-shrink-0 place-items-center rounded-[6px]">
              <Image
                src={item.spec.icon_url}
                alt={`${item.spec.name} icon`}
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
      accessor: "provider_spec_name",
      header: t("provider"),
    },
    {
      accessor: "model_instances",
      header: t("models"),
      render: (value: ModelInstance[]) => <ModelsList models={value || []} />,
    },
    {
      accessor: "managed_by",
      header: "",
      render: () => (
        <Badge
          variant="success"
          size="sm"
          className="w-fit bg-green-50 text-green-700 border-green-200"
        >
          {badgeLabel}
        </Badge>
      ),
    },
  ];

  if (viewMode === "table") {
    return <Table data={configs} columns={configColumns} />;
  }

  return (
    <div className={CARD_GRID_DENSE}>
      {configs.map((config) => (
        <PlatformProviderConfigCard
          key={config.id}
          config={config}
          badgeLabel={badgeLabel}
        />
      ))}
    </div>
  );
}

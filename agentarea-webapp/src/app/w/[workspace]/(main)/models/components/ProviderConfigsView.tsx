"use client";

import Image from "next/image";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
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
  const tEmpty = useTranslations("Models.empty");
  const tCommon = useTranslations("Common");
  const tAdmin = useTranslations("AdminOnly");
  const router = useWorkspaceRouter();
  const { canAdminister } = useViewerCapabilities();

  // Define table columns for configs
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
          <span className="truncate font-medium">{value}</span>
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
          title={
            hasNoData
              ? tEmpty("noOwnConfigs.title")
              : tEmpty("noMatchingConfigs")
          }
          description={
            hasNoData
              ? tEmpty("noOwnConfigs.description")
              : tEmpty("noMatchingConfigsDescription", { query: searchQuery })
          }
          hints={
            hasNoData
              ? [
                  canAdminister
                    ? {
                        text: tEmpty("noOwnConfigs.hintAdd"),
                        href: "/models/create",
                      }
                    : { text: tAdmin("hints.manageProvider") },
                  { text: tEmpty("noOwnConfigs.hintEnable") },
                  { text: tEmpty("noOwnConfigs.hintSecret") },
                ]
              : undefined
          }
          iconsType="llm"
          action={
            hasNoData
              ? canAdminister
                ? { label: tEmpty("addProvider"), href: "/models/create" }
                : undefined
              : { label: tCommon("clearSearch"), href: "/models" }
          }
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
            `/models/edit/${config.id}`
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

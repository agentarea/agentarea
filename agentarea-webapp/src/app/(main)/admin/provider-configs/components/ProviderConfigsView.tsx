"use client";

import { useMemo } from "react";
import { Cpu } from "lucide-react";
import CollectionView, {
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import ModelsList from "./ModelsList";
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
  const items = useMemo<CollectionItem[]>(
    () =>
      configs.map((config) => {
        const iconUrl = (config as any).spec?.icon_url as string | undefined;
        return {
          id: config.id,
          color: "#5e6ad2",
          icon: iconUrl ? (
            <img
              src={iconUrl}
              alt=""
              aria-hidden="true"
              className="h-4 w-4 rounded object-contain dark:invert"
            />
          ) : (
            Cpu
          ),
          title: config.name,
          href: `/admin/provider-configs/edit/${config.id}`,
          badges: (config as any).provider_spec_name
            ? [{ label: (config as any).provider_spec_name, color: "#5e6ad2" }]
            : [],
          meta: (
            <ModelsList models={(config as any).model_instances || []} />
          ),
        };
      }),
    [configs]
  );

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

  return (
    <CollectionView
      view={viewMode === "table" ? "list" : "grid"}
      items={items}
      bleed
    />
  );
}

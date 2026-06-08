"use client";

import { useMemo } from "react";
import { Cpu } from "lucide-react";
import CollectionView, {
  type CollectionItem,
} from "@/components/CollectionView";
import EmptyState from "@/components/EmptyState";
import ModelsList from "./ModelsList";
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
  const items = useMemo<CollectionItem[]>(
    () =>
      specs.map((spec) => {
        const iconUrl = (spec as any).icon_url as string | undefined;
        return {
          id: spec.id,
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
          title: spec.name,
          description: (spec as any).description,
          href: `/admin/provider-configs/create/${spec.id}`,
          meta: <ModelsList models={(spec as any).models || []} />,
        };
      }),
    [specs]
  );

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

  return (
    <CollectionView
      view={viewMode === "table" ? "list" : "grid"}
      items={items}
      bleed
    />
  );
}

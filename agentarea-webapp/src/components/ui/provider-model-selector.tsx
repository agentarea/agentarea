"use client";

import * as React from "react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { Bot } from "lucide-react";
import type { ModelInstanceResponse } from "@/api/client/types.gen";
import { ModelTags } from "@/components/ModelTags";
import {
  GroupedSelect,
  type GroupedSelectGroup,
} from "@/components/ui/grouped-select";

type LLMModelInstance = ModelInstanceResponse;

export interface ProviderModelSelectorProps {
  modelInstances: LLMModelInstance[];
  value?: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  emptyMessage?: string | React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onAddProvider?: () => void;
}

function ProviderIcon({
  providerName,
  iconUrl,
}: {
  providerName: string;
  iconUrl?: string | null;
}) {
  if (!iconUrl) return <Bot className="h-4 w-4 text-muted-foreground" />;
  return (
    <span className="avatar-plate grid h-5 w-5 flex-shrink-0 place-items-center rounded-[5px]">
      <Image
        src={iconUrl}
        alt={providerName}
        width={16}
        height={16}
        className="h-[13px] w-[13px] object-contain"
        onError={(e) => {
          e.currentTarget.style.display = "none";
        }}
      />
    </span>
  );
}

/** Models grouped by the provider configuration they run through. */
export function ProviderModelSelector({
  modelInstances,
  value,
  onValueChange,
  placeholder,
  disabled = false,
  className,
  emptyMessage,
  open,
  onOpenChange,
  onAddProvider,
}: ProviderModelSelectorProps) {
  const t = useTranslations("ModelSelector");

  const groups = React.useMemo(() => {
    const byConfig = new Map<string, LLMModelInstance[]>();
    for (const instance of modelInstances) {
      const configName = instance.config_name || t("defaultConfiguration");
      byConfig.set(configName, [...(byConfig.get(configName) ?? []), instance]);
    }
    return [...byConfig].map(([configName, instances]): GroupedSelectGroup => {
      const providerName = instances[0]?.provider_name || t("unknownProvider");
      return {
        id: configName,
        label: configName,
        description: providerName,
        icon: (
          <ProviderIcon
            providerName={providerName}
            iconUrl={instances[0]?.provider_icon_url}
          />
        ),
        items: instances.map((instance) => ({
          id: instance.id,
          label: instance.name,
          icon: (
            <ProviderIcon
              providerName={instance.provider_name || ""}
              iconUrl={instance.provider_icon_url}
            />
          ),
          end: <ModelTags tags={instance.tags} />,
        })),
      };
    });
  }, [modelInstances, t]);

  return (
    <GroupedSelect
      groups={groups}
      value={value}
      onValueChange={onValueChange}
      placeholder={placeholder ?? t("placeholder")}
      groupsTitle={t("configurations")}
      itemsTitle={t("models")}
      searchPlaceholder={t("search")}
      noResults={t("noModels")}
      emptyMessage={emptyMessage ?? t("noModels")}
      onAddGroup={onAddProvider}
      disabled={disabled}
      className={className}
      open={open}
      onOpenChange={onOpenChange}
    />
  );
}

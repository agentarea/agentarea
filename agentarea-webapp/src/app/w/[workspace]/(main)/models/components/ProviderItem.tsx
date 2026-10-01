import { AlertCircle, Check } from "lucide-react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import ModelsList from "./ModelsList";
import type { ProviderSpecWithModelsResponse } from "@/api/client/types.gen";
import { ProviderConfig } from "./types";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

interface ProviderConfigCardProps {
  config: ProviderConfig;
}

export function ProviderConfigCard({ config }: ProviderConfigCardProps) {
  const t = useTranslations("Models");
  const modelInstances = config.model_instances || [];

  return (
    <LinkedCard
      href={`/models/edit/${config.id}`}
      title={config.name}
      icon={config.spec?.icon_url}
      type="edit"
      subtitle={
        <p className="w-full truncate text-xs text-muted-foreground">
          {config.spec?.name}
        </p>
      }
    >
      {modelInstances.length > 0 ? (
        <ModelsList models={modelInstances} />
      ) : (
        <Badge variant="yellow" size="sm" className="w-fit">
          <AlertCircle className="h-3 w-3" />
          {t("noInstancesConfigured")}
        </Badge>
      )}
    </LinkedCard>
  );
}

interface PlatformProviderConfigCardProps {
  config: ProviderConfig;
  badgeLabel: string;
}

// Platform-supplied configs aren't the customer's to edit or delete, and the
// API rejects writes to them anyway -- so unlike ProviderConfigCard this is
// plain markup, not LinkedCard: no href, no cursor-pointer, no Edit affordance.
export function PlatformProviderConfigCard({
  config,
  badgeLabel,
}: PlatformProviderConfigCardProps) {
  const modelInstances = config.model_instances || [];

  return (
    <Card className="flex h-full flex-col justify-between px-4 py-4">
      <div className="mb-2 flex items-start gap-3">
        {config.spec?.icon_url ? (
          <span className="avatar-plate grid h-10 w-10 flex-shrink-0 place-items-center rounded-lg">
            <Image
              src={config.spec.icon_url}
              alt={`${config.spec.name} icon`}
              width={24}
              height={24}
              className="h-6 w-6 object-contain"
            />
          </span>
        ) : null}
        <div className="min-w-0 flex-1 pt-0.5">
          <h4 className="truncate text-[15px] font-medium leading-tight tracking-tight text-zinc-900 dark:text-zinc-100">
            {config.name}
          </h4>
          <p className="truncate text-xs text-muted-foreground">
            {config.spec?.name}
          </p>
        </div>
      </div>

      <div className="mt-auto flex flex-col gap-2 py-2">
        {modelInstances.length > 0 && <ModelsList models={modelInstances} />}
        <Badge
          variant="success"
          size="sm"
          className="w-fit bg-green-50 text-green-700 border-green-200"
        >
          <Check className="mr-1 h-3 w-3" />
          {badgeLabel}
        </Badge>
      </div>
    </Card>
  );
}

interface ProviderSpecCardProps {
  spec: ProviderSpecWithModelsResponse;
}

// Catalog entry on the Available tab, laid out like ProviderConfigCard: the
// provider key under the name and the first models it offers.
export function ProviderSpecCard({ spec }: ProviderSpecCardProps) {
  const models = spec.models.map((model) => ({
    model_display_name: model.display_name,
    model_name: model.model_name,
    provider_name: spec.name,
    provider_icon_url: spec.icon_url,
  }));

  return (
    <LinkedCard
      href={`/models/create/${spec.id}`}
      title={spec.name}
      icon={spec.icon_url ?? undefined}
      type="config"
      subtitle={
        <p className="w-full truncate text-xs text-muted-foreground">
          {spec.provider_key}
        </p>
      }
    >
      {models.length > 0 ? <ModelsList models={models} /> : null}
    </LinkedCard>
  );
}

import { AlertCircle, Check } from "lucide-react";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import ModelsList from "./ModelsList";
import { ProviderConfig, ProviderSpec } from "./types";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

interface ProviderConfigCardProps {
  config: ProviderConfig;
}

export function ProviderConfigCard({ config }: ProviderConfigCardProps) {
  const modelInstances = config.model_instances || [];

  return (
    <LinkedCard
      href={`/admin/provider-configs/edit/${config.id}`}
      title={config.name}
      icon={config.spec?.icon_url}
      invertIconInDark={true}
      type="edit"
      subtitle={
        <p className="truncate text-xs text-gray-500 w-full">
          {config.spec?.name}
        </p>
      }
    >
      {modelInstances.length > 0 ? (
        <ModelsList models={modelInstances} />
      ) : (
        <Badge
          variant="secondary"
          className="w-fit bg-yellow-50 text-yellow-700 hover:bg-yellow-100 border-yellow-200"
          size="sm"
        >
          <AlertCircle className="mr-1 h-3 w-3" />
          No instances configured
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
          <p className="truncate text-xs text-gray-500">{config.spec?.name}</p>
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
  spec: ProviderSpec;
}

export function ProviderSpecCard({ spec }: ProviderSpecCardProps) {
  return (
    <LinkedCard
      className="py-3"
      href={`/admin/provider-configs/create/${spec.id}`}
      title={spec.name}
      icon={spec.icon_url}
      invertIconInDark={true}
      type="config"
    />
  );
}

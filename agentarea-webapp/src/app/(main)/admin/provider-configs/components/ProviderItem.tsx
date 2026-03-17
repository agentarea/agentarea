import { AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
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

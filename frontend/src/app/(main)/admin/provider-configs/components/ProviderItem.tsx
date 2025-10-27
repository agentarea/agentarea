import Link from "next/link";
import { AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import ModelsList from "./ModelsList";
import { ProviderConfig, ProviderSpec } from "./types";

interface ProviderConfigCardProps {
  config: ProviderConfig;
}

export function ProviderConfigCard({ config }: ProviderConfigCardProps) {
  const modelInstances = config.model_instances || [];

  return (
    <Link
      href={`/admin/provider-configs/create?provider_spec_id=${config.id}&isEdit=true`}
    >
      <Card className="h-full px-4 py-4">
        <div className="mb-2 flex gap-2">
          {config.spec?.icon_url && (
            <img
              src={config.spec.icon_url}
              alt={`${config.spec.name} icon`}
              className="h-5 w-5 rounded dark:invert"
            />
          )}
          <div className="min-w-0 flex-1">
            <h4 className="truncate">{config.name}</h4>
            <p className="truncate text-xs text-gray-500">
              {config.spec?.name}
            </p>
          </div>
        </div>

        {/* Display Model Instances */}
        {modelInstances.length > 0 ? (
          <ModelsList models={modelInstances} />
        ) : (
          <Badge variant="yellow" className="w-fit" size="sm">
            <AlertCircle className="mr-1 h-3 w-3" />
            No instances configured
          </Badge>
        )}
      </Card>
    </Link>
  );
}

interface ProviderSpecCardProps {
  spec: ProviderSpec;
}

export function ProviderSpecCard({ spec }: ProviderSpecCardProps) {
  return (
    <Link href={`/admin/provider-configs/create?provider_spec_id=${spec.id}`}>
      <Card className="h-full px-4 py-4">
        <div className="flex items-center gap-2">
          {spec.icon_url && (
            <img
              src={spec.icon_url}
              alt={`${spec.name} icon`}
              className="h-5 w-5 rounded dark:invert"
            />
          )}
          <div className="min-w-0 flex-1">
            <h4 className="truncate">{spec.name}</h4>
            {/* <p className="text-sm text-gray-500">{spec.provider_key}</p> */}
          </div>
        </div>
      </Card>
    </Link>
  );
}

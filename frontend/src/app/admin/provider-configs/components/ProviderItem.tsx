import { ProviderConfig, ProviderSpec } from "./types";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { AlertCircle } from "lucide-react";
import ModelsList from "./ModelsList";
import { Card } from "@/components/ui/card";

interface ProviderConfigCardProps {
    config: ProviderConfig;
}

export function ProviderConfigCard({ config }: ProviderConfigCardProps) {
    const modelInstances = config.model_instances || [];
    
    return (
        <Link href={`/admin/provider-configs/create?provider_spec_id=${config.id}&isEdit=true`}>
            <Card className="px-4 py-5 h-full">
                <div className="flex gap-2 mb-2">
                    {config.spec?.icon_url && (
                        <img 
                            src={config.spec.icon_url} 
                            alt={`${config.spec.name} icon`} 
                            className="w-6 h-6 rounded dark:invert"
                        />
                    )}
                    <div className="flex-1 min-w-0">
                        <h4 className="truncate">{config.name}</h4>
                        <p className="text-xs text-gray-500 truncate">{config.spec?.name}</p>
                    </div>
                </div>
                
                {/* Display Model Instances */}
                {modelInstances.length > 0 ? (
                    <ModelsList models={modelInstances} />
                ) : (
                    <Badge variant="yellow" className="w-fit" size="sm">
                        <AlertCircle className="h-3 w-3 mr-1" />
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
            <Card className="px-4 py-5 h-full">
                <div className="flex items-center gap-2">
                    {spec.icon_url && (
                        <img 
                            src={spec.icon_url} 
                            alt={`${spec.name} icon`} 
                            className="w-6 h-6 rounded dark:invert"
                        />
                    )}
                    <div className="flex-1 min-w-0">
                        <h4 className="truncate">{spec.name}</h4>
                        {/* <p className="text-sm text-gray-500">{spec.provider_key}</p> */}
                    </div>
                </div>
            </Card>
        </Link>
    );
}


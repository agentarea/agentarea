import { ArrowRight, AlertCircle } from "lucide-react";
import { ProviderConfig, ProviderSpec, ModelInstance } from "../provider-configs/page";
import ModelsList from "./ModelsList";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";

type CardContentProps = {
    item: ProviderSpec | ProviderConfig;
    type?: 'provider-spec' | 'provider-config';
}

export default function CardContent({ item }: CardContentProps) {
    const t = useTranslations("Models");
    // Determine if item is ProviderSpec or ProviderConfig
    const isProviderSpec = 'provider_key' in item;
    const itemData: ProviderSpec = isProviderSpec ? item as ProviderSpec : (item as ProviderConfig).spec;
    const providerConfig = isProviderSpec ? null : item as ProviderConfig;

    return (
        <div className="flex flex-col justify-between h-full group">
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3 mb-2">
                {itemData.icon_url && (
                    <img 
                        src={itemData.icon_url} 
                        alt={`${itemData.name} icon`} 
                        className="w-8 h-8 rounded dark:invert"
                    />
                )}
                <div className="flex-1">
                    <div className="font-[500] text-[16px] font-montserrat">
                        {item.name}
                    </div>
                    <div className="text-xs text-muted-foreground">{itemData.provider_key}</div>
                </div>
            </div>
            <div className="text-[14px] opacity-50 line-clamp-2">
                {itemData.description || 'No description'}
            </div>            
            {/* Display Model Instances for Provider Configs */}
            {providerConfig ? (
                // For provider configs, show only the actual model instances
                providerConfig.model_instances && providerConfig.model_instances.length > 0 ? (
                    <ModelsList models={providerConfig.model_instances} />
                ) : (
                    <Badge variant="yellow" className="w-fit">
                        <AlertCircle className="h-3 w-3 mr-1" />
                        {t("noInstancesConfigured")}
                    </Badge>
                )
            ) : (
                // For provider specs, show all available models
                <ModelsList models={itemData.models} />
            )}
        </div>
        <div className="flex gap-2 -mr-2 -mb-3 mt-2 justify-end">
            <div className="small-link opacity-0 group-hover:opacity-100">
                {isProviderSpec ? t("configureProvider") : t("editConfiguration")}
                <ArrowRight className="h-4 w-4" />
            </div>
        </div>
    </div>
    )
}
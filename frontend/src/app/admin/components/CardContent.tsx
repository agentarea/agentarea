import { ArrowRight } from "lucide-react";
import { ProviderConfig, ProviderSpec } from "../provider-configs/page";
import ModelsList from "./ModelsList";
import { useTranslations } from "next-intl";

type CardContentProps = {
    item: ProviderSpec | ProviderConfig;
    type?: 'provider-spec' | 'provider-config';
}

export default function CardContent({ item }: CardContentProps) {
    const t = useTranslations("Models");
    // Determine if item is ProviderSpec or ProviderConfig
    const isProviderSpec = 'provider_key' in item;
    const itemData: ProviderSpec = isProviderSpec ? item as ProviderSpec : (item as ProviderConfig).spec;

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
            {itemData.models && <ModelsList models={itemData.models} />}
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
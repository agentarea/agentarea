'use client';

import HeaderTabs from "@/components/HeaderTabs";
import { LayoutDashboardIcon, TablePropertiesIcon } from "lucide-react";
import { useTranslations } from "next-intl";

export default function ProviderHeaderTabs() {
    const t = useTranslations("Common");
    
    return (
        <HeaderTabs 
            tabs={[
                {
                    value: 'grid',
                    label: t('grid'),
                    icon: <LayoutDashboardIcon className="w-4 h-4" />
                },
                {
                    value: 'table',
                    label: t('table'),
                    icon: <TablePropertiesIcon className="w-4 h-4" />
                }
            ]}
            paramName="tab"
            defaultTab="grid"
        />
    );
}


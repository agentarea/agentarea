'use client';

import { Tabs } from "@/components/ui/tabs";
import { useRouter } from "next/navigation";

export function TabsWithNavigation({ 
    activeTab, 
    children,
    routeChange
}: { 
    activeTab: string;
    children: React.ReactNode;
    routeChange: string;
}) {
    const router = useRouter();


    return (
        <Tabs 
            value={activeTab} 
            className="w-full" 
            defaultValue="grid"
            onValueChange={(value) => {
                router.push(`${routeChange}?tab=${value}`);
            }}
        >
            {children}
        </Tabs>
    );
} 
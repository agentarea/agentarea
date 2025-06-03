'use client';

import { Tabs } from "@/components/ui/tabs";
import { useRouter } from "next/navigation";

export function TabsWithNavigation({ 
    activeTab, 
    children 
}: { 
    activeTab: string;
    children: React.ReactNode;
}) {
    const router = useRouter();
    
    return (
        <Tabs 
            value={activeTab} 
            className="w-full" 
            defaultValue="grid"
            onValueChange={(value) => {
                router.push(`/admin/llms?tab=${value}`);
            }}
        >
            {children}
        </Tabs>
    );
} 
"use client"

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { LayoutDashboardIcon, TablePropertiesIcon, SearchIcon } from "lucide-react";
import { useState, useEffect } from "react";
import GridView from "./components/GridView";
import { list } from "./data";
import TableView from "./components/TableView";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";

// Client component that handles the tab rendering
export default function AddLLMModelPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    
    // Get tab from URL query params first (SSR and CSR safe)
    const tabFromUrl = searchParams.get("tab");
    
    // Initialize activeTab state once on component mount
    const [activeTab, setActiveTab] = useState<string>(() => {
        // First try URL query params (works on initial load and browser back/forward)
        if (tabFromUrl && (tabFromUrl === "grid" || tabFromUrl === "table")) {
            return tabFromUrl;
        }
        
        // Then try localStorage (client-side only)
        if (typeof window !== "undefined") {
            const savedTab = localStorage.getItem("llm-browse-tab");
            if (savedTab && (savedTab === "grid" || savedTab === "table")) {
                return savedTab;
            }
        }
        
        // Default fallback
        return "grid";
    });

    // Update URL and localStorage when tab changes
    useEffect(() => {
        // Skip first render
        if (typeof window === "undefined") return;
        
        // Update localStorage
        localStorage.setItem("llm-browse-tab", activeTab);
        
        // Update URL without full page reload
        const url = new URL(window.location.href);
        url.searchParams.set("tab", activeTab);
        router.replace(url.pathname + url.search, { scroll: false });
    }, [activeTab, router]);

    const handleTabChange = (value: string) => {
        setActiveTab(value);
    };

    return (
        <div className="content">
            <div className="content-header">
                <h1>
                    LLM Models
                </h1>
            </div>

            <Tabs 
                value={activeTab} 
                className="w-full" 
                onValueChange={handleTabChange}
                defaultValue="grid"
            >
                <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
                   <div className="flex flex-row items-center gap-[5px] flex-1">
                        <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
                            <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                <SearchIcon className="h-4 w-4" />
                            </div>
                            <Input 
                                placeholder="Search"
                                className="pl-9 w-full" 
                            />
                    </div>
                </div>

                <div 
                    // className="md:flex-1 text-right"
                >
                    <TabsList>
                        <TabsTrigger value="grid" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]"><LayoutDashboardIcon className="w-5 h-5" /> <span className="hidden sm:block">Grid</span></TabsTrigger>
                        <TabsTrigger value="table" className="flex flex-row items-center gap-[8px] px-[10px] sm:px-[20px]"><TablePropertiesIcon className="w-5 h-5" /> <span className="hidden sm:block">Table</span></TabsTrigger>
                    </TabsList>
                </div>
                
                </div>

                <TabsContent value="grid">
                    <GridView list={list} />
                </TabsContent>
                <TabsContent value="table">
                    <TableView list={list}/>
                </TabsContent>
            </Tabs>
        </div>
    )
}

"use client"
import { cn } from "@/lib/utils";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { LayoutDashboardIcon, TablePropertiesIcon, SearchIcon } from "lucide-react";
import { useState } from "react";
import GridView from "./components/GridView";
import { list } from "./data";
export default function AddLLMModelPage() {
    const [activeTab, setActiveTab] = useState("grid");

    return (
        <div className="content">
            <div className="content-header">
                <h1>
                    LLM Models
                </h1>
            </div>


            <Tabs defaultValue={activeTab} className="w-full" onValueChange={setActiveTab}>
                <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
                   <div className="flex flex-row items-center gap-[5px] flex-1">
                        <div className="relative w-full md:w-[200px] focus-within:w-full max-w-full transition-all duration-300">
                            <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                                <SearchIcon className="h-4 w-4" />
                            </div>
                            <Input 
                                placeholder="Search"
                                className="pl-9 w-full" 
                            />
                    </div>
                </div>

                <div className="md:flex-1 text-right">
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
                    TABLE
                </TabsContent>
            </Tabs>
        </div>
    )
}

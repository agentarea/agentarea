import { cn } from "@/lib/utils";
import { Clock, DollarSign, TrendingUp, Info } from "lucide-react";
interface StatCardProps {
    children: React.ReactNode;
    type?: "timer" | "money" | "kpi" | "info";
}

export default function StatCard({ children, type }: StatCardProps) {
    // return (
    //     <div className={cn(
    //         "card border-none card-shadow flex flex-row gap-2 py-2 items-center relative", 
    //         type === "timer" && "bg-[#dae5fc] text-[#3d349b]", 
    //         type === "money" && "bg-[#e2f7e1] text-[#2d7a2f]", 
    //         type === "kpi" && "bg-[#f0e6ff] text-[#6b34b3]", 
    //     )}>
    //         <img src={`/${type}.svg`} className="absolute top-1 right-1 w-10 h-10" />
    //         {/* {
    //             type === "timer" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><Clock className="h-8 w-8 text-primary"/></div> :
    //             type === "money" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><DollarSign className="h-8 w-8 text-green-500"/></div> :
    //             type === "kpi" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><TrendingUp className="h-8 w-8 text-yellow-500"/></div> :
    //             <div className="w-10 h-10 rounded-md flex items-center justify-center "><Info className="h-8 w-8 text-blue-500"/></div>
    //         } */}

    //         <div className="flex flex-col gap-0">
    //             <div className="text-xs">
    //                 {
    //                     type === "timer" ? "Time" :
    //                     type === "money" ? "Usage" :
    //                     type === "kpi" ? "KPI" :
    //                     "Info"
    //                 }
    //             </div>
                
    //             {children}
    //         </div>
    //     </div>
    // )

    return (
        <div className="flex flex-col">
            <div className={cn("bg-red-500 rounded-t-lg h-8 text-xs -mb-3 w-max px-3 py-1 flex gap-1", 
                type === "timer" && "bg-[#dae5fc] text-[#3d349b]", 
                type === "money" && "bg-[#e2f7e1] text-[#2d7a2f]", 
                type === "kpi" && "bg-[#f0e6ff] text-[#6b34b3]")
            }>
                {
                    type === "timer" ? <Clock className="h-3 w-3 mt-0.5"/> :
                    type === "money" ? <DollarSign className="h-3 w-3 mt-0.5"/> :
                    type === "kpi" ? <TrendingUp className="h-3 w-3 mt-0.5"/> :
                    <Info className="h-3 w-3 mt-0.5"/> 
                }
                {
                    type === "timer" ? "Time" :
                    type === "money" ? "Usage" :
                    type === "kpi" ? "KPI" :
                    "Info"
                }
            </div>
            <div className={cn(
                "card card-shadow flex flex-row gap-2 py-2 items-center relative", 
                "flex-1"
            )}>
                {/* <img src={`/${type}.svg`} className="absolute top-1 right-1 w-10 h-10" /> */}
                {/* {
                    type === "timer" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><Clock className="h-8 w-8 text-primary"/></div> :
                    type === "money" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><DollarSign className="h-8 w-8 text-green-500"/></div> :
                    type === "kpi" ? <div className="w-10 h-10 rounded-md flex items-center justify-center "><TrendingUp className="h-8 w-8 text-yellow-500"/></div> :
                    <div className="w-10 h-10 rounded-md flex items-center justify-center "><Info className="h-8 w-8 text-blue-500"/></div>
                } */}

                <div className="flex flex-col gap-0">
                    {/* <div className="text-xs">
                        {
                            type === "timer" ? "Time" :
                            type === "money" ? "Usage" :
                            type === "kpi" ? "KPI" :
                            "Info"
                        }
                    </div> */}
                    
                    {children}
                </div>
            </div>
        </div>
        
    )
}
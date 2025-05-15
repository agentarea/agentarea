import { ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"

export default function SectionTitle({children, isCollapsed, onClick, expanded}: {children: React.ReactNode, isCollapsed?: boolean, onClick?: () => void, expanded?: boolean}) {
    
    return (
        <>
            <div className={cn(
                "whitespace-nowrap uppercase text-[10px] font-medium text-zinc-400 flex flex-row items-center gap-[6px]",
                isCollapsed && "cursor-pointer hover:text-zinc-500 group transition-all duration-300"
            )}
                onClick={onClick}
            >
                <div className="w-full flex flex-row items-center gap-[6px]">
                    {children}
                    <div className={cn(
                        "h-[1px] w-full bg-zinc-200/50 dark:bg-zinc-700",
                        isCollapsed && "group-hover:bg-zinc-300 dark:group-hover:bg-zinc-600 transition-all duration-300"
                    )} />
                </div>
                {isCollapsed && (
                    <ChevronDown className={cn("w-4 h-4 transition-all duration-300 group-hover:text-zinc-500", expanded ? "rotate-180" : "rotate-0"    )} />
                )}
            </div>
        </>
    );
}
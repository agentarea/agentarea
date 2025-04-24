import { cn } from "@/lib/utils";
import { LLMModel } from "../data";

export default function GridView({list}: {list: LLMModel[]}) {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-[12px]">                
                {list.map((item) => (
                    <div key={item.id} className="card card-shadow group">
                        <div className="flex flex-row items-start gap-[16px]">
                            <div className={cn("h-[45px] min-w-[45px] w-[45px] rounded-md overflow-hidden group-hover:scale-105 transition-all duration-300 p-[3px]", item.image ? "dark:bg-white" : "bg-zinc-200 dark:bg-zinc-700")}>
                                {
                                    item.image && (
                                        <img src={item.image} alt={item.name} className="object-contain w-full h-full rounded-md"/>
                                    )
                                }
                            </div>
                            <div className="flex flex-col justify-center">
                                <div className="font-[500] text-[16px] font-montserrat">{item.name}</div>
                                <div className="text-[14px] text-accent">{item.category}</div>
                            </div>
                        </div>
                        <div className="text-[14px] opacity-50 line-clamp-2 pt-[10px]">
                            {item.description}
                        </div>
                    </div>
                ))}
            </div>
    )
}
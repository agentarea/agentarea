import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export default function ModelsList({ models }: { models: any[] }) {
    return (
        <div>
            {models && models.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                    {models.slice(0, 2).map((model, index) => (
                        <Badge key={index} variant="default" className={cn(models.length === 1 ? 'max-w-full' : 'max-w-[110px]')}>
                            <span className="block overflow-hidden text-ellipsis whitespace-nowrap">
                                {model.display_name || model.model_name || model.name|| 'Unknown'}
                            </span>
                        </Badge>
                    ))}
                    {models.length > 2 && (
                        <span className="text-xs opacity-60 ml-1">+{models.length - 2}</span>
                    )}
                </div>
            )}
        </div>
    );
}
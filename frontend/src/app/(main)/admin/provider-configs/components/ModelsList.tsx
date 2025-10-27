import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export default function ModelsList({ models }: { models: any[] }) {
  return (
    <div>
      {models && models.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {models.slice(0, 2).map((model, index) => (
            <Badge
              key={index}
              variant="default"
              size="sm"
              className={cn(
                models.length === 1 ? "max-w-full" : "max-w-[110px]"
              )}
            >
              <span className="block overflow-hidden text-ellipsis whitespace-nowrap">
                {model.model_display_name ||
                  model.display_name ||
                  model.model_name ||
                  model.name ||
                  "Unknown"}
              </span>
            </Badge>
          ))}
          {models.length > 2 && (
            <span className="ml-1 text-xs opacity-60">
              +{models.length - 2}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

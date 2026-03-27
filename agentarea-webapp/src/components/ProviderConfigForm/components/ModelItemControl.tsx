import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { ModelSpec } from "@/types/provider";

type ModelItemControlProps = {
  model: ModelSpec;
  isSelected: boolean;
  onSelect: (isSelected: boolean) => void;
};

export const ModelItemControl = ({
  model,
  isSelected,
  onSelect,
}: ModelItemControlProps) => {
  return (
    <div className="card-item space-y-2 px-3 py-2">
      <div className="flex gap-2">
        <Checkbox
          checked={isSelected}
          onCheckedChange={onSelect}
          aria-label="Toggle model"
          className="mt-1 min-w-[16px]"
          id={`model-${model.id}`}
        />
        <Label
          className="flex w-full cursor-pointer flex-col items-start justify-between gap-2 sm:flex-row sm:items-center md:flex-col md:items-start lg:flex-row lg:items-center"
          htmlFor={`model-${model.id}`}
        >
          <div className="flex flex-col gap-1">
            <div className="text-sm font-medium">{model.display_name}</div>
            <div className="text-xs text-muted-foreground/50">
              {model.description}
            </div>
          </div>
          <div className="flex items-center justify-start gap-2 sm:gap-3">
            <div className="note">
              {model.context_window.toLocaleString()} tokens
            </div>
            <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
            <div className="note">$0/M input tokens</div>
            <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
            <div className="note">$0/M output tokens</div>
          </div>
        </Label>
      </div>
    </div>
  );
};

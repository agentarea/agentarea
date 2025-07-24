import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Switch } from "@/components/ui/switch";
// import FormLabel from "@/components/FormLabel/FormLabel";
// import { Input } from "@/components/ui/input";
// import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

type modelControlProps = {
  model: any | undefined;
  isSelected: boolean;
  onSelect: (isSelected: boolean) => void;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
}

export const ModelItemControl = ({ model, isSelected, onSelect }: modelControlProps) => {
    return (
        <div className="card-item px-3 py-2 flex gap-2">
            <Switch
                size="xs"
                checked={isSelected}
                onCheckedChange={onSelect}
                aria-label="Toggle model"
                className="mt-1 min-w-[28px]"
                id={`model-${model.id}`}
            />
            <Label className="
                flex gap-2 justify-between w-full cursor-pointer
                flex-col sm:flex-row md:flex-col lg:flex-row   
                tems-start sm:items-center md:items-start lg:items-center "
                htmlFor={`model-${model.id}`}
            >
                <div className="flex flex-col gap-1">
                    <div className="text-sm font-medium">{model.display_name}</div>
                    <div className="text-xs text-muted-foreground/50">{model.description}</div>
                </div>
                <div className="flex items-center justify-start gap-2 sm:gap-3">
                    <div className="note">{model.context_window.toLocaleString()} tokens</div>
                    <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
                    <div className="note">$0/M input tokens</div>
                    <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
                    <div className="note">$0/M output tokens</div>
                </div>
            </Label>
        </div>

        
        // <div className="card-item px-3 py-2 flex items-center justify-between">
        //     <div className="flex flex-col gap-2">
        //         <div className="flex flex-col md:flex-row gap-1 md:gap-7 md:items-center">
        //             <div className="text-sm font-medium">{model.display_name}</div>
        //             <div className="text-xs text-muted-foreground/50">{model.description}</div>
        //         </div>
        //         <div className="flex items-center justify-start gap-2 sm:gap-3">
        //             <div className="note">{model.context_window.toLocaleString()} tokens</div>
        //             <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
        //             <div className="note">$0/M input tokens</div>
        //             <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
        //             <div className="note">$0/M output tokens</div>
        //         </div>
        //     </div>

        //     <div className="flex items-center gap-1">
        //         <span
        //             className="note cursor-pointer select-none hidden sm:block"
        //             onClick={() => onSelect(!isSelected)}
        //         >
        //             {isSelected ? "enabled" : "disabled"}
        //         </span>
        //         <Switch
        //             size="xs"
        //             checked={isSelected}
        //             onCheckedChange={onSelect}
        //             aria-label="Toggle model"
        //         />
        //     </div>
        // </div>



        // <CardAccordionItem
        //     className="data-[state=open]:border-border dark:data-[state=open]:border-zinc-700"
        //     value={`model-${model.id}`}
        //     controls={controls}
        //     title={model.display_name}
            
        // >
        //     <div className="gap-2 pl-3 pb-3 cursor-default">
        //         <div className="note text-sm">{model.description}</div>
        //         {/* {model.context_window && (
        //             <Badge variant="outline">
        //                 {model.context_window.toLocaleString()} tokens
        //             </Badge>
        //         )} */}

        //         <div className="flex items-center justify-start gap-2 sm:gap-3 lg:gap-1 xl:gap-3 pt-2">
        //             <div className="note">{model.context_window.toLocaleString()} tokens</div>
        //             <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
        //             <div className="note">$0/M input tokens</div>
        //             <div className="h-[15px] w-[1px] bg-zinc-300 dark:bg-zinc-700" />
        //             <div className="note">$0/M output tokens</div>
        //         </div>
        //         {/* <div className="flex flex-col gap-2 pt-2">
        //             <div className="space-y-2">
        //                 <FormLabel htmlFor={`name-${model.id}`}>Instance Name</FormLabel>
        //                 <Input
        //                     id={`name-${model.id}`}
        //                     value={model.instanceName}
        //                 //  onChange={(e) => updateSelectedModel(model.id, { instanceName: e.target.value })}
        //                     placeholder="Model instance name"
        //                 />
        //             </div>
        //             <div className="space-y-2">
        //                 <FormLabel htmlFor={`desc-${model.id}`}>Description (Optional)</FormLabel>
        //                 <Textarea
        //                     id={`desc-${model.id}`}
        //                     value={model.description}
        //                 //  onChange={(e) => updateSelectedModel(model.id, { description: e.target.value })}
        //                     placeholder="Describe this model instance..."
        //                     rows={2}
        //                 />
        //             </div>
        //         </div> */}
        //     </div>
        // </CardAccordionItem>
    );
};
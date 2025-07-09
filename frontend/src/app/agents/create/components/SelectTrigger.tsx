import { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Plus } from "lucide-react";
import { Accordion } from "@/components/ui/accordion";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";

type TriggerOption = {
  id: string;
  label: string;
  icon?: React.ReactNode;
};

type SelectTriggerProps = {
  triggerOptions: TriggerOption[];
  onAdd: (option: TriggerOption) => void;
  onRemove: (triggerId: string) => void;
  acceptedTriggers: string[];
  openTriggerId?: string | null;
};

export default function SelectTrigger({
  triggerOptions,
  onAdd,
  onRemove,
  acceptedTriggers,
  openTriggerId,
}: SelectTriggerProps) {
  const [accordionValue, setAccordionValue] = useState<string>("");

  useEffect(() => {
    if (openTriggerId) setAccordionValue(`trigger-${openTriggerId}`);
    else setAccordionValue("");
  }, [openTriggerId]);

  return (
    <Accordion
      type="single"
      collapsible
      className="flex flex-col flex-1 overflow-y-auto space-y-2 pb-[40px]"
      value={accordionValue}
      onValueChange={setAccordionValue}
    >
      {triggerOptions.map((opt) => {
        const isAccepted = acceptedTriggers.includes(opt.id);
        const controls = isAccepted ? (
          <Badge
            variant="destructive"
            onClick={() => onRemove(opt.id)}
            className="cursor-pointer border hover:border-destructive"
          >
            ✕ Remove
          </Badge>
        ) : (
          <Badge
            variant="light"
            onClick={() => onAdd(opt)}
            className="cursor-pointer border hover:border-primary hover:text-primary dark:hover:bg-primary dark:hover:text-white"
          >
            <Plus className="h-4 w-4" /> Add
          </Badge>
        );

        return (
          <CardAccordionItem
            key={opt.id}
            value={`trigger-${opt.id}`}
            id={`trigger-${opt.id}`}
            title={opt.label}
            iconSrc="/Icon.svg"
            controls={controls}
          >
            <div className="p-4 text-sm text-muted-foreground">Description</div>
          </CardAccordionItem>
        );
      })}
    </Accordion>
  );
} 
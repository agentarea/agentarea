import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { HelpCircle, Plus } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

type AccordionControlProps = {
  id: string;
  accordionValue: string;
  setAccordionValue: (value: string) => void;
  eventFields: any[];
  removeEvent: (index: number) => void;
  title: React.ReactNode;
  children: React.ReactNode;
  note?: string | React.ReactNode;
  addText?: string;
  onAdd?: () => void;
};

export default function AccordionControl({id, accordionValue, setAccordionValue, eventFields, removeEvent, onAdd, title, children, note, addText}: AccordionControlProps) {
  return (
    <div className="flex flex-row gap-2">
        <Accordion 
            type="single" 
            collapsible 
            className="w-full"
            value={accordionValue}
            onValueChange={setAccordionValue}
        >
            <AccordionItem value={id} className="border-none">
                <AccordionTrigger className="flex flex-row gap-2 py-0 justify-start"
                    controls={
                        <div className="flex flex-row gap-2">
                            {note && (
                                <TooltipProvider>
                                    <Tooltip delayDuration={300}>
                                        <TooltipTrigger asChild>
                                        <HelpCircle className="h-6 min-w-4 w-4 hover:text-primary text-muted-foreground transition-colors duration-300" />
                                    </TooltipTrigger>
                                    <TooltipContent className="max-w-xs">
                                        {note}
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                            )}

                            <Button 
                                type="button" 
                                size="xs"
                                onClick={onAdd}
                            >
                                <Plus />
                                {addText ? addText : "Add"}
                            </Button>
                        </div>
                    }
                >
                    {title}
                </AccordionTrigger>
                <AccordionContent className="p-0">
                    {children}
                </AccordionContent>
            </AccordionItem>
        </Accordion>
    </div>
  );
}
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { HelpCircle, Plus } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

type AccordionControlProps = {
  id: string;
  accordionValue: string;
  setAccordionValue: (value: string) => void;
  title: React.ReactNode;
  children: React.ReactNode;
  note?: string | React.ReactNode;
  addText?: string;
  onAdd: (id: string) => void;
  dropdownItems: {
    id: string;
    label: string;
    icon: React.ReactNode;
  }[];
};

export default function AccordionControl({id, accordionValue, setAccordionValue, onAdd, title, children, note, addText, dropdownItems}: AccordionControlProps) {
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

                            {/* <Button 
                                type="button" 
                                size="xs"
                                onClick={onAdd}
                            >
                                <Plus />
                                {addText ? addText : "Add"}
                            </Button> */}
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <Button 
                                        className="focus-visible:ring-0"
                                        type="button" 
                                        size="xs"
                                    >
                                        <Plus />
                                        {addText ? addText : "Add"}
                                    </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent>
                                    {/* <DropdownMenuLabel>My Account</DropdownMenuLabel> */}
                                    {/* <DropdownMenuSeparator /> */}
                                    {
                                        dropdownItems?.map((item) => (
                                            <DropdownMenuItem key={item.id} onClick={() => onAdd(item.id)}>
                                                {item.icon}
                                                {item.label}
                                            </DropdownMenuItem>
                                        ))
                                    }
                                </DropdownMenuContent>
                            </DropdownMenu>
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
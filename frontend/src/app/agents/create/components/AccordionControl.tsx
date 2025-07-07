import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { HelpCircle, Plus } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

type DropdownItem = {
  id: string;
  label: string;
  icon: React.ReactNode;
};

type DropdownControlProps = {
    addText?: string;
    onAdd: (id: string) => void;
    dropdownItems: DropdownItem[];
}

type CustomControlProps = {
    mainControl: React.ReactNode;
}

type AccordionControlProps = {
  id: string;
  accordionValue: string;
  setAccordionValue: (value: string) => void;
  title: React.ReactNode;
  children: React.ReactNode;
  note?: string | React.ReactNode;
} & (DropdownControlProps | CustomControlProps);



export default function AccordionControl({ id, accordionValue, setAccordionValue, title, children, note, ...props }: AccordionControlProps) {
  const isDropdown = "dropdownItems" in props;

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
                <AccordionTrigger className="label py-0 justify-start pb-4"
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
                            {
                                isDropdown ? (
                                <DropdownMenu>
                                    <DropdownMenuTrigger asChild>
                                        <Button 
                                            className="focus-visible:ring-0"
                                            type="button" 
                                            size="xs"
                                        >
                                            <Plus />
                                            {isDropdown && props.addText ? props.addText : "Add"}
                                        </Button>
                                    </DropdownMenuTrigger>
                                    <DropdownMenuContent>
                                        {isDropdown &&
                                          props.dropdownItems.map((item: DropdownItem) => (
                                            <DropdownMenuItem 
                                                key={item.id} 
                                                onClick={() => props.onAdd(item.id)}
                                                className="flex flex-row items-center gap-2 cursor-pointer"
                                            >
                                                <div className="w-4 h-4 min-w-4">{item.icon}</div>
                                                <div className="text-sm font-light">{item.label}</div>
                                            </DropdownMenuItem>
                                          ))}
                                    </DropdownMenuContent>
                                </DropdownMenu>
                                ) : (
                                  (props as CustomControlProps).mainControl
                                )
                            }
                            
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
import { HelpCircle, Plus } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type DropdownItem = {
  id: string;
  label: string;
  icon: React.ReactNode;
};

type DropdownControlProps = {
  addText?: string;
  onAdd: (id: string) => void;
  dropdownItems: DropdownItem[];
};

type CustomControlProps = {
  mainControl: React.ReactNode;
};

type AccordionControlProps = {
  id: string;
  accordionValue: string;
  setAccordionValue: (value: string) => void;
  title: React.ReactNode;
  children: React.ReactNode;
  note?: string | React.ReactNode;
  triggerClassName?: string;
  chevron?: React.ReactNode;
  itemClassName?: string;
} & (DropdownControlProps | CustomControlProps);

export default function AccordionControl({
  id,
  accordionValue,
  setAccordionValue,
  title,
  children,
  note,
  triggerClassName,
  chevron,
  itemClassName,
  ...props
}: AccordionControlProps) {
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
        <AccordionItem value={id} className={cn(itemClassName)}>
          <AccordionTrigger
            className={cn("label justify-start py-0", triggerClassName)}
            chevron={chevron}
            controls={
              <div className="flex flex-row items-center gap-2">
                {note && (
                  <TooltipProvider>
                    <Tooltip delayDuration={300}>
                      <TooltipTrigger asChild>
                        <HelpCircle className="h-6 w-4 min-w-4 text-muted-foreground transition-colors duration-300 hover:text-primary" />
                      </TooltipTrigger>
                      <TooltipContent className="max-w-xs">
                        {note}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
                {isDropdown ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        className="focus-visible:ring-0"
                        type="button"
                        size="sm"
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
                            className="flex cursor-pointer flex-row items-center gap-2"
                          >
                            <div className="h-4 w-4 min-w-4">{item.icon}</div>
                            <div className="text-sm font-light">
                              {item.label}
                            </div>
                          </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  (props as CustomControlProps).mainControl
                )}
              </div>
            }
          >
            {title}
          </AccordionTrigger>
          <AccordionContent className="pt-4">{children}</AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

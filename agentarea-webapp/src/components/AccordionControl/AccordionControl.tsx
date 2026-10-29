import { ChevronRight, HelpCircle, Plus } from "lucide-react";
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
  /** The add button's look; a quieter one where several sit on a page. */
  addVariant?: React.ComponentProps<typeof Button>["variant"];
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
  /** How many items the section holds, read even while it is collapsed. */
  count?: number;
  /** The note as a muted line under the title, instead of behind a "?". */
  noteInline?: boolean;
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
  count,
  noteInline = false,
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
            // Drawn below, right after the title, so a count reads apart from it.
            chevron={null}
            controls={
              <div className="flex flex-row items-center gap-2">
                {note && !noteInline && (
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
                      {/* Sized like the ConfigSheet trigger beside it. */}
                      <Button
                        className="gap-1.5 focus-visible:ring-0"
                        type="button"
                        size="xs"
                        variant={props.addVariant}
                      >
                        <Plus className="h-4 w-4" />
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
            {chevron ?? (
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-data-[state=open]:rotate-90" />
            )}
            {!!count && (
              <span className="rounded-full bg-muted px-1.5 text-[11px] font-medium leading-4 tabular-nums text-muted-foreground no-underline dark:bg-zinc-800">
                {count}
              </span>
            )}
          </AccordionTrigger>
          {note && noteInline && (
            // Read even while the section is collapsed, like its count.
            <div className="note mt-1 space-y-0.5">{note}</div>
          )}
          <AccordionContent className="pt-4">{children}</AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

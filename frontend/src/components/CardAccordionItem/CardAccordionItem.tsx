import React from "react";
import { AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * CardAccordionItem – reusable accordion item with unified card visuals
 *
 * Usage:
 * <Accordion type="single|multiple"> // root managed by parent
 *   <CardAccordionItem
 *      value="unique-value"
 *      title={<div className="...">...</div>}
 *      controls={<MyControls />}
 *   >
 *      ...accordion content here...
 *   </CardAccordionItem>
 * </Accordion>
 */
export type CardAccordionItemProps = {
  /** value passed to Radix AccordionItem */
  value: string;
  /** Title text or custom node */
  title: React.ReactNode | string;
  /** Icon source path (used only if title is string). Optional */
  iconSrc?: string;
  /** optional DOM id for scroll targeting */
  id?: string;
  /** Optional element rendered to the far right – e.g. buttons, switches */
  controls?: React.ReactNode;
  /** Inner collapsible content */
  children?: React.ReactNode;
  /** Additional className for AccordionItem */
  className?: string;
  /** Additional className for AccordionTrigger */
  triggerClassName?: string;
  /** Override default chevron */
  chevron?: React.ReactNode;
};

export function CardAccordionItem({
  value,
  id: htmlId,
  title,
  iconSrc,
  controls,
  children,
  className,
  triggerClassName,
  chevron,
}: CardAccordionItemProps) {

  const generatedControls = controls;

  // Build default title node if title is plain text
  const titleNode = typeof title === "string" ? (
    <div className="flex flex-row items-center gap-2 px-[7px] py-[7px]">
      {iconSrc && <img src={iconSrc} className="w-5 h-5" />}
      <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent dark:group-hover:text-accent group-data-[state=open]:text-accent dark:group-data-[state=open]:text-accent">
        {title}
      </h3>
    </div>
  ) : (
    title
  );

  return (
    <AccordionItem
      value={value}
      id={htmlId}
      className={cn(
        "border border-border rounded-md transition-colors pr-[7px] data-[state=open]:border-accent",
        className
      )}
    >
      <AccordionTrigger
        className={cn(
          "group w-max flex flex-row gap-2 py-0 justify-start rotate-0 hover:no-underline [&[data-state=open]>svg]:rotate-90 [&[data-state=open]>svg]:text-accent",
          triggerClassName
        )}
        controls={generatedControls}
        chevron={
          chevron || (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all duration-300 group-hover:text-accent" />
          )
        }
      >
        {titleNode}
      </AccordionTrigger>
      {children && (
        <AccordionContent className="px-[7px] py-[7px]">
          {children}
        </AccordionContent>
      )}
    </AccordionItem>
  );
} 
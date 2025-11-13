import React from "react";
import { ChevronRight } from "lucide-react";
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
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
  onHeaderClick?: () => void;
  headerClassName?: string;
  hideChevron?: boolean;
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
  onHeaderClick,
  headerClassName,
  hideChevron = false,
}: CardAccordionItemProps) {
  const generatedControls = controls;

  // Build default title node if title is plain text
  const titleNode =
    typeof title === "string" ? (
      <div
        className={cn(
          "flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]",
          headerClassName
        )}
      >
        {iconSrc && <img src={iconSrc} alt="" className="h-4 w-4 shrink-0" />}
        <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
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
      className={cn("card-item data-[state=open]:border-accent", className)}
    >
      <AccordionTrigger
        className={cn(
          "group flex w-max rotate-0 flex-row justify-start gap-2 py-0 hover:no-underline",
          triggerClassName
        )}
        controls={generatedControls}
        chevron={
          hideChevron
            ? null
            : chevron || (
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all duration-300 group-hover:text-accent group-data-[state=open]:rotate-90" />
              )
        }
        onClick={onHeaderClick}
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

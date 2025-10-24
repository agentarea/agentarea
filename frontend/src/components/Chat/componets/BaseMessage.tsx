import { ChevronUp } from "lucide-react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/utils";

type BaseMessageProps = {
  children: React.ReactNode;
  headerLeft?: React.ReactNode;
  headerRight?: React.ReactNode;
  collapsed?: boolean;
  isUser?: boolean;
};

const BaseMessage = ({
  children,
  headerLeft,
  headerRight,
  collapsed,
  isUser,
}: BaseMessageProps) => {
  return (
    <Accordion
      type="single"
      collapsible
      className="w-full max-w-full lg:max-w-[80%]"
      defaultValue={collapsed ? undefined : "item-1"}
    >
      <AccordionItem
        value="item-1"
        className={cn(
          "w-full rounded-xl border data-[state=open]:shadow-sm dark:border-zinc-700",
          isUser ? "bg-primary/10" : "bg-chatBackground"
        )}
      >
        <AccordionTrigger className="px-2 py-1 text-sm hover:no-underline">
          <div className="flex w-full flex-row items-center justify-between">
            <div className="">{headerLeft}</div>
            <div className="flex items-center gap-2 text-xs font-normal text-gray-400">
              {headerRight}
            </div>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <div className="whitespace-pre-wrap rounded-xl border-t bg-white px-2 py-4 text-sm leading-relaxed text-text/70 dark:border-zinc-700 dark:bg-zinc-900">
            {children}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
};

export default BaseMessage;

import { ChevronUp } from "lucide-react";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { cn } from "@/lib/utils";

type BaseMessageProps = {
  children: React.ReactNode;
  headerLeft?: React.ReactNode;
  headerRight?: React.ReactNode;
  collapsed?: boolean;
  isUser?: boolean;
};

const BaseMessage = ( { children, headerLeft, headerRight, collapsed, isUser }: BaseMessageProps ) => {
  return (
    <Accordion type="single" collapsible className="w-full max-w-[60%]" defaultValue={collapsed ? undefined : "item-1"}>
      <AccordionItem value="item-1" className={cn("w-full border rounded-xl dark:border-zinc-700 data-[state=open]:shadow-sm", isUser ? "bg-primary/10" : "bg-chatBackground")}>
        <AccordionTrigger className="px-2 py-1 text-sm hover:no-underline">
          <div className="w-full flex flex-row items-center justify-between">
              <div className="">
                  {headerLeft}
              </div>
              <div className="flex items-center gap-2 text-gray-400">
                  {headerRight}
              </div>
          </div>
        </AccordionTrigger>
        <AccordionContent>
          <div className="bg-white text-text/70 border-t rounded-xl px-2 py-4 dark:bg-zinc-900 dark:border-zinc-700 whitespace-pre-wrap leading-relaxed text-sm">
            {children}
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
};

export default BaseMessage;
import { ChevronUp } from "lucide-react";
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";

type BaseMessageProps = {
  children: React.ReactNode;
  headerLeft?: React.ReactNode;
  headerRight?: React.ReactNode;
  collapsed?: boolean;
};

const BaseMessage = ( { children, headerLeft, headerRight, collapsed }: BaseMessageProps ) => {
  return (
    <Accordion type="single" collapsible className="w-full max-w-[60%]" defaultValue={collapsed ? undefined : "item-1"}>
      <AccordionItem value="item-1">
        <div className="w-full bg-zinc-100 border rounded-lg dark:bg-zinc-900 dark:border-zinc-700">
          <AccordionTrigger className="px-2 py-1 text-sm text-gray-400">
            <div className="w-full flex flex-row items-center justify-between">
                <div>
                    {headerLeft}
                </div>
                <div className="flex items-center gap-2">
                    {headerRight}
                </div>
            </div>
          </AccordionTrigger>
          <AccordionContent>
            <div className="bg-white border-t rounded-lg px-2 py-4 dark:bg-zinc-800 dark:border-zinc-700 whitespace-pre-wrap leading-relaxed text-sm">
              {children}
            </div>
          </AccordionContent>
        </div>
      </AccordionItem>
    </Accordion>
  );
};

export default BaseMessage;
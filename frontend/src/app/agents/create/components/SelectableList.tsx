import { useState, useEffect } from "react";
import { Accordion } from "@/components/ui/accordion";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Badge } from "@/components/ui/badge";
import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";

interface SelectableListProps<T extends { id: string }> {
  /** Collection of items to render */
  items: T[];
  /** How to display an item's title */
  extractTitle: (item: T) => string;
  /** Optional icon extractor */
  extractIconSrc?: (item: T) => string;
  /** Called when user clicks Add */
  onAdd: (item: T) => void;
  /** Called when user clicks Remove */
  onRemove: (item: T) => void;
  /** Optional custom accordion body */
  renderContent?: (item: T) => React.ReactNode;
  /** Currently selected IDs */
  selectedIds: string[];
  /** Item to auto-open */
  openItemId?: string | null;
  /** Accordion item prefix */
  prefix?: string;
  /** Translation namespace – defaults to 'AgentsPage' */
  translationNamespace?: string;
  /** Label (button) for active items */
  activeLabel?: string | React.ReactNode;
  /** Label (button) for inactive items */
  inactiveLabel?: string | React.ReactNode;
}

export function SelectableList<T extends { id: string }>({
  items,
  extractTitle,
  extractIconSrc = () => "/Icon.svg",
  onAdd,
  onRemove,
  renderContent = () => null,
  selectedIds,
  openItemId,
  prefix = "item",
  translationNamespace = "AgentsPage",
  activeLabel,
  inactiveLabel,
}: SelectableListProps<T>) {
  const [accordionValue, setAccordionValue] = useState<string[]>([]);
  const t = useTranslations(translationNamespace);

  // Keep accordion in sync with externally provided openItemId
  useEffect(() => {
    if (openItemId) {
      setAccordionValue([`${prefix}-${openItemId}`]);
    } else {
      setAccordionValue([]);
    }
  }, [openItemId, prefix]);

  return (
    <Accordion
      type="multiple"
      className="flex flex-col space-y-2 pb-[30px]"
      value={accordionValue}
      onValueChange={setAccordionValue}
    >
      {items.map((item) => (
          <CardAccordionItem
            key={item.id}
            value={`${prefix}-${item.id}`}
            id={`${prefix}-${item.id}`}
            title={extractTitle(item)}
            iconSrc={extractIconSrc(item)}
            controls={
              selectedIds.includes(item.id) ? (
                <Badge
                  variant="destructive"
                  onClick={() => onRemove(item)}
                  className="cursor-pointer border hover:border-destructive"
                >
                  {activeLabel || <><X className="h-4 w-4" /> {t("create.remove")}</>} 
                </Badge>
              ) : (
                <Badge
                  variant="light"
                  onClick={() => onAdd(item)}
                  className="cursor-pointer border hover:border-primary hover:text-primary dark:hover:bg-primary dark:hover:text-white"
                >
                  {inactiveLabel || <><Plus className="h-4 w-4" /> {t("create.add")}</>}
                </Badge>
              )
            }
          >
            {renderContent(item)}
          </CardAccordionItem>
        ))}
    </Accordion>
  );
} 
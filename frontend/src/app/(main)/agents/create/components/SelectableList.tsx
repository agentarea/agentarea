import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Accordion } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";

interface SelectableListProps<T extends { id: string }> {
  items: T[];
  extractTitle: (item: T) => string | React.ReactNode;
  extractIconSrc?: (item: T) => string;
  onAdd: (item: T) => void;
  onRemove: (item: T) => void;
  renderContent?: (item: T) => React.ReactNode;
  selectedIds: string[];
  openItemId?: string | null;
  prefix?: string;
  translationNamespace?: string;
  activeLabel?: string | React.ReactNode;
  inactiveLabel?: string | React.ReactNode;
  disableExpand?: boolean;
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
  disableExpand = false,
}: SelectableListProps<T>) {
  const [accordionValue, setAccordionValue] = useState<string[]>([]);
  const t = useTranslations(translationNamespace);

  useEffect(() => {
    if (openItemId && !disableExpand) {
      setAccordionValue([`${prefix}-${openItemId}`]);
    } else {
      setAccordionValue([]);
    }
  }, [openItemId, prefix, disableExpand]);

  const handleHeaderClick = (item: T) => {
    if (selectedIds.includes(item.id)) return;
    onAdd(item);
  };

  return (
    <Accordion
      type="multiple"
      className="flex flex-col space-y-2 pb-[30px]"
      value={disableExpand ? [] : accordionValue}
      onValueChange={disableExpand ? undefined : setAccordionValue}
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
                className={
                  disableExpand
                    ? "cursor-pointer border group-hover:border-destructive group-hover:bg-destructive group-hover:text-white"
                    : "cursor-pointer border hover:border-destructive"
                }
              >
                {activeLabel || (
                  <>
                    <X className="h-4 w-4" /> {t("create.remove")}
                  </>
                )}
              </Badge>
            ) : (
              <Badge
                variant="light"
                onClick={() => onAdd(item)}
                className={
                  disableExpand
                    ? "cursor-pointer border group-hover:border-primary group-hover:text-primary dark:group-hover:bg-primary dark:group-hover:text-white"
                    : "cursor-pointer border hover:border-primary hover:text-primary dark:hover:bg-primary dark:hover:text-white"
                }
              >
                {inactiveLabel || (
                  <>
                    <Plus className="h-4 w-4" /> {t("create.add")}
                  </>
                )}
              </Badge>
            )
          }
          onHeaderClick={
            disableExpand ? () => handleHeaderClick(item) : undefined
          }
          headerClassName={disableExpand ? "cursor-pointer" : undefined}
          hideChevron={disableExpand}
        >
          {disableExpand ? null : renderContent(item)}
        </CardAccordionItem>
      ))}
    </Accordion>
  );
}

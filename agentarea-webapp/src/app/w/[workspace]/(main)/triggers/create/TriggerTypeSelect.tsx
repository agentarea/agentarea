"use client";

import { useTranslations } from "next-intl";
import {
  GroupedSelect,
  type GroupedSelectGroup,
} from "@/components/ui/grouped-select";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/**
 * Up to this many types fit a plain dropdown; past it the types are picked
 * like models are, kinds on the left and a search over both.
 */
const PLAIN_SELECT_MAX_TYPES = 6;

/**
 * The trigger type picker. The types come grouped by kind either way, so a
 * catalog that grows a type per integration only changes how they are shown.
 */
export function TriggerTypeSelect({
  id,
  groups,
  value,
  onValueChange,
  placeholder,
  disabled = false,
  invalid = false,
}: {
  id: string;
  groups: GroupedSelectGroup[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
  invalid?: boolean;
}) {
  const t = useTranslations("TriggersPage.create");
  const items = groups.flatMap((group) =>
    group.items.map((item) => ({ ...item, icon: item.icon ?? group.icon }))
  );

  if (items.length > PLAIN_SELECT_MAX_TYPES) {
    return (
      <GroupedSelect
        id={id}
        groups={groups}
        value={value}
        onValueChange={onValueChange}
        placeholder={placeholder}
        groupsTitle={t("typeKinds")}
        itemsTitle={t("typeItems")}
        searchPlaceholder={t("typeSearch")}
        noResults={t("typeNotFound")}
        showGroupInValue={false}
        disabled={disabled}
        invalid={invalid}
      />
    );
  }

  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger
        id={id}
        className="md:max-w-sm"
        aria-invalid={invalid || undefined}
      >
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.id} value={item.id}>
            <span className="flex items-center gap-2">
              <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                {item.icon}
              </span>
              {item.label}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

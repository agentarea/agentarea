"use client";

import { useTranslations } from "next-intl";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { EgressExitOption } from "../egress-exit";

// A select item cannot carry "", so leaving directly has a value of its own.
const DIRECT = "direct";

/** Pick the exit a container connection leaves through, or none. */
export function EgressExitSelect({
  id,
  exits,
  value,
  onChange,
  disabled,
}: {
  id?: string;
  exits: EgressExitOption[];
  value: string | null;
  onChange: (exitId: string | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("EgressExits.picker");

  return (
    <Select
      value={value ?? DIRECT}
      onValueChange={(next) => onChange(next === DIRECT ? null : next)}
      disabled={disabled}
    >
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DIRECT}>{t("direct")}</SelectItem>
        {exits.map((exit) => (
          <SelectItem key={exit.id} value={exit.id}>
            {exit.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

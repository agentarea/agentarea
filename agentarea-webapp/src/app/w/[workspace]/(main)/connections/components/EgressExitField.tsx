"use client";

import { useTranslations } from "next-intl";
import { Waypoints } from "lucide-react";
import FormLabel from "@/components/FormLabel/FormLabel";
import SectionLoadError from "@/components/SectionLoadError";
import type { EgressExitChoices } from "../egress-exit";
import { EgressExitSelect } from "./EgressExitSelect";

/** The create forms' field for the exit a new container connection leaves through. */
export function EgressExitField({
  id,
  choices,
  value,
  onChange,
}: {
  id: string;
  choices: EgressExitChoices;
  value: string | null;
  onChange: (exitId: string | null) => void;
}) {
  const t = useTranslations("EgressExits.picker");
  return (
    <div className="grid gap-2">
      <FormLabel htmlFor={id} icon={Waypoints} optional>
        {t("label")}
      </FormLabel>
      {choices.ok ? (
        <>
          <EgressExitSelect
            id={id}
            exits={choices.exits}
            value={value}
            onChange={onChange}
          />
          <p className="note">{t("hint")}</p>
        </>
      ) : (
        <SectionLoadError message={choices.message} />
      )}
    </div>
  );
}

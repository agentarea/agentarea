"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Languages,
  LayoutTemplate,
  ShieldCheck,
  SlidersHorizontal,
  type LucideIcon,
} from "lucide-react";
import {
  Control,
  Controller,
  FieldErrors,
  UseFormRegister,
  useWatch,
  type Path,
} from "react-hook-form";
import AccordionControl from "@/components/AccordionControl";
import FormLabel from "@/components/FormLabel/FormLabel";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { AgentFormValues } from "../types";
import { getNestedErrorMessage } from "../utils/formUtils";
import { SelectedItemRow } from "./SelectedItemRow";

type BehaviorConfigProps = {
  register: UseFormRegister<AgentFormValues>;
  control: Control<AgentFormValues>;
  errors: FieldErrors<AgentFormValues>;
};

/** One switch the agent runs with, as a row: what it is and why to turn it on. */
function BehaviorSwitch({
  control,
  name,
  id,
  icon: Icon,
  title,
  description,
  children,
}: {
  control: Control<AgentFormValues>;
  name: Path<AgentFormValues>;
  id: string;
  icon: LucideIcon;
  title: ReactNode;
  description: ReactNode;
  /** Shown under the row while the switch is on. */
  children?: ReactNode;
}) {
  const on = Boolean(useWatch({ control, name }));
  return (
    <SelectedItemRow
      open={on}
      stacked
      avatar={
        <EntityAvatar
          variant="soft"
          size={24}
          iconScale={0.45}
          icon={<Icon strokeWidth={1.85} />}
          aria-hidden
        />
      }
      title={
        <label htmlFor={id} className="cursor-pointer">
          {title}
        </label>
      }
      subtitle={description}
      end={
        <Controller
          name={name}
          control={control}
          render={({ field }) => (
            <Switch
              id={id}
              checked={Boolean(field.value)}
              onCheckedChange={field.onChange}
            />
          )}
        />
      }
    >
      {children}
    </SelectedItemRow>
  );
}

const BehaviorConfig = ({ register, control, errors }: BehaviorConfigProps) => {
  const t = useTranslations("AgentsPage.create");
  const [accordionValue, setAccordionValue] = useState("behavior");
  const languageError = getNestedErrorMessage(errors, "answer_check.language");
  // A refused save opens the section, so the field it points at is seen.
  useEffect(() => {
    if (languageError) setAccordionValue("behavior");
  }, [languageError]);

  return (
    <AccordionControl
      id="behavior"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={SlidersHorizontal} className="cursor-pointer">
          {t("behavior.title")}
        </FormLabel>
      }
      note={t("behavior.note")}
      mainControl={null}
    >
      <div className="overflow-hidden rounded-md border">
        <BehaviorSwitch
          control={control}
          name="a2ui_enabled"
          id="a2ui_enabled"
          icon={LayoutTemplate}
          title={t("a2ui")}
          description={t("a2uiDescription")}
        />
        <BehaviorSwitch
          control={control}
          name="answer_check.enabled"
          id="answer_check_enabled"
          icon={ShieldCheck}
          title={t("answerCheck")}
          description={t("answerCheckDescription")}
        >
          <div className="space-y-2 md:max-w-sm">
            <FormLabel htmlFor="answer_check_language" icon={Languages}>
              {t("answerCheckLanguage")}
            </FormLabel>
            <Input
              id="answer_check_language"
              {...register("answer_check.language")}
              placeholder={t("answerCheckLanguagePlaceholder")}
              aria-invalid={!!languageError}
            />
            {languageError && <p className="form-error">{languageError}</p>}
          </div>
        </BehaviorSwitch>
      </div>
    </AccordionControl>
  );
};

export default BehaviorConfig;

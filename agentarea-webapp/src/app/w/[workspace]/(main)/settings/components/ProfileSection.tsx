"use client";

import { useTranslations } from "next-intl";
import {
  getNodeId,
  getNodeLabel,
  UiNodeGroupEnum,
  type UiNode,
} from "@ory/client-fetch";
import { useOryFlow } from "@ory/elements-react";
import { useFormContext, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { Input } from "@/components/ui/input";
import { deterministicHue } from "@/lib/avatar-hue";
import { displayName } from "@/lib/display-name";
import { FieldErrors, FlowSuccess, MethodSubmit, OryText } from "./FlowParts";
import { errorsOf, fieldNodes, submitAccepted } from "./oryNodes";
import SettingsRow from "./SettingsRow";
import { SettingsFooter, SettingsSection } from "./SettingsSection";

/** Our copy and treatment for the traits of the identity schema; any other trait keeps Kratos' label. */
const TRAITS: Record<
  string,
  {
    label: "email" | "firstName" | "lastName" | "username";
    hint?: "emailHint";
    readOnly?: boolean;
    leading?: string;
  }
> = {
  "traits.email": { label: "email", hint: "emailHint", readOnly: true },
  "traits.name.first": { label: "firstName" },
  "traits.name.last": { label: "lastName" },
  "traits.username": { label: "username", leading: "@" },
};

/** Greys out a read-only field (the email) and leaves the others alone. */
const FIELD_CLASS =
  "read-only:bg-muted/50 read-only:text-muted-foreground dark:read-only:bg-muted/50";

export default function ProfileSection({ nodes }: { nodes: UiNode[] }) {
  const t = useTranslations("SettingsPage.profile");
  const tCommon = useTranslations("Common");
  const { flow } = useOryFlow();
  const {
    register,
    reset,
    formState: { isDirty, isSubmitting, isSubmitSuccessful },
  } = useFormContext();
  const saved = isSubmitSuccessful && submitAccepted(flow, nodes);

  return (
    <SettingsSection title={t("personalInfo")}>
      <IdentityHead />
      {fieldNodes(nodes).map((node) => {
        const { name, type, required, autocomplete } = node.attributes;
        const trait = TRAITS[name];
        const label = getNodeLabel(node);
        const title = trait
          ? t(trait.label)
          : label && <OryText message={label} />;
        const id = `settings-${name}`;
        return (
          <SettingsRow
            key={getNodeId(node)}
            htmlFor={id}
            control="field"
            title={title || name}
            description={trait?.hint && t(trait.hint)}
          >
            <Input
              id={id}
              type={type}
              required={required}
              autoComplete={autocomplete}
              readOnly={trait?.readOnly}
              leading={trait?.leading}
              aria-invalid={errorsOf(node.messages).length > 0 || undefined}
              className={FIELD_CLASS}
              {...register(name)}
            />
            <FieldErrors messages={node.messages} />
          </SettingsRow>
        );
      })}
      <SettingsFooter
        status={
          isDirty ? (
            <span className="font-medium text-foreground">{t("unsaved")}</span>
          ) : saved ? (
            <FlowSuccess />
          ) : (
            t("saved")
          )
        }
      >
        {isDirty && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={isSubmitting}
            onClick={() => reset()}
          >
            {t("discard")}
          </Button>
        )}
        <MethodSubmit method={UiNodeGroupEnum.Profile} disabled={!isDirty}>
          {tCommon("save")}
        </MethodSubmit>
      </SettingsFooter>
    </SettingsSection>
  );
}

/** Avatar, name and @username as they read now, edits included. */
function IdentityHead() {
  const [first, last, username, email] = useWatch({
    name: [
      "traits.name.first",
      "traits.name.last",
      "traits.username",
      "traits.email",
    ],
  }) as (string | undefined)[];
  const name = displayName({ name: { first, last }, username, email });

  return (
    <div className="flex items-center gap-3 border-b border-border/60 bg-muted/20 px-4 py-3.5">
      <EntityAvatar
        size={44}
        variant="pigment"
        hue={deterministicHue(email || name || "")}
        text={nameInitials(name)}
        aria-hidden
      />
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold">{name}</div>
        {username && (
          <div className="truncate font-mono text-xs text-muted-foreground">
            @{username}
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Waypoints } from "lucide-react";
import FormError from "@/components/FormError";
import {
  SectionCard,
  SectionCardHead,
} from "@/components/Overview/OverviewCard";
import SectionLoadError from "@/components/SectionLoadError";
import { bindEgressExitAction } from "../[id]/actions";
import type { EgressExitChoices } from "../egress-exit";
import { EgressExitSelect } from "./EgressExitSelect";
import { SectionEditAction } from "./SectionEditAction";

/**
 * Which egress exit a container connection leaves the internet through, so
 * its outbound traffic comes from that exit's address. A section card of the
 * connection overview, edited in place like its cost.
 */
export function EgressExitSection({
  instanceId,
  boundExitId,
  choices,
}: {
  instanceId: string;
  boundExitId: string | null;
  choices: EgressExitChoices;
}) {
  const t = useTranslations("EgressExits.section");
  const [draft, setDraft] = useState<{ exitId: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  const bound = choices.ok
    ? choices.exits.find((exit) => exit.id === boundExitId)
    : undefined;

  const save = () =>
    startSaving(async () => {
      if (!draft) return;
      const result = await bindEgressExitAction(instanceId, draft.exitId);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setError(null);
      setDraft(null);
    });

  return (
    <SectionCard>
      <SectionCardHead
        icon={<Waypoints />}
        title={t("title")}
        action={
          choices.ok ? (
            <SectionEditAction
              open={draft !== null}
              hasRows
              busy={saving}
              onOpen={() => {
                setError(null);
                // An exit no longer listed has no row to show; start from none.
                setDraft({ exitId: bound?.id ?? null });
              }}
              onCancel={() => setDraft(null)}
              onSave={save}
              saveLabel={t("save")}
            />
          ) : undefined
        }
      />
      <div className="space-y-3 px-[15px] py-3">
        {!choices.ok ? (
          <div className="[&>div]:mb-0">
            <SectionLoadError message={choices.message} />
          </div>
        ) : draft !== null ? (
          <>
            <EgressExitSelect
              exits={choices.exits}
              value={draft.exitId}
              onChange={(exitId) => setDraft({ exitId })}
              disabled={saving}
            />
            <p className="note">{t("restartHint")}</p>
            {error && <FormError>{error}</FormError>}
          </>
        ) : (
          <p className="text-[12.5px]">
            {!boundExitId
              ? t("direct")
              : bound
                ? bound.platform
                  ? t("boundPlatform", { name: bound.name })
                  : bound.name
                : t("unknown", { id: boundExitId })}
          </p>
        )}
      </div>
    </SectionCard>
  );
}

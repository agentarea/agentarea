import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listSecrets } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getEgressExits } from "@/lib/egress-exits";
import AddEgressExitButton from "./AddEgressExitButton";
import type { SecretChoices } from "./EgressExitFormDialog";
import EgressExitsClient from "./EgressExitsClient";

export const metadata: Metadata = {
  title: "Egress exits",
};

// The secrets the proxy password may be read from, for the add/edit form.
async function secretChoices(failed: string): Promise<SecretChoices> {
  const result = await listSecrets();
  if (result.error || !result.data) {
    console.error("Failed to load secrets for egress exits", result.error);
    return { ok: false, message: apiErrorMessage(result, failed) };
  }
  return {
    ok: true,
    secrets: result.data.map(({ id, name }) => ({ id, name })),
  };
}

export default async function EgressExitsPage() {
  const [t, tSettings, state] = await Promise.all([
    getTranslations("EgressExits"),
    getTranslations("SettingsPage"),
    getEgressExits(),
  ]);
  // A deployment without egress exits has no such page.
  if (state.status === "none") notFound();
  // Started here, awaited by the form only when it opens.
  const secrets = secretChoices(t("form.passwordLoadFailed"));

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tSettings("title"), href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
        controls:
          state.status === "ready" ? (
            <AddEgressExitButton secrets={secrets} />
          ) : undefined,
      }}
    >
      {state.status === "ready" ? (
        <EgressExitsClient exits={state.exits} secrets={secrets} />
      ) : (
        <RetryEmptyState
          title={t("loadFailed")}
          description={apiErrorMessage(state.failure, t("loadFailed"))}
        />
      )}
    </ContentBlock>
  );
}

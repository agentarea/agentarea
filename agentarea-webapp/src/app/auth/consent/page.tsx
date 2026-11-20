import Image from "next/image";
import { getTranslations } from "next-intl/server";
import { Check, TriangleAlert } from "lucide-react";
import { AuthLayout } from "@/components/auth/auth-layout";
import { Card } from "@/components/ui/card";
import { getOAuthConsent } from "@/lib/api";
import { getWorkspaces } from "@/lib/workspace-context";
import { ConsentForm } from "./ConsentForm";
import { redirectTarget } from "./redirect-target";

const KNOWN_SCOPES = ["openid", "offline_access"] as const;

export default async function ConsentPage({
  searchParams,
}: {
  searchParams: Promise<{ consent_challenge?: string }>;
}) {
  const t = await getTranslations("AuthConsent");
  const { consent_challenge: challenge } = await searchParams;
  const consent = challenge ? (await getOAuthConsent(challenge)).data : null;

  if (!challenge || !consent) {
    return (
      <ConsentCard title={t("title", { clientName: t("defaultClient") })}>
        <div className="text-destructive border-destructive/30 bg-destructive/5 rounded-md border px-3 py-2 text-sm">
          {challenge ? t("error.loadFailed") : t("error.missingChallenge")}
        </div>
      </ConsentCard>
    );
  }

  const clientName =
    consent.client.client_name || consent.client.client_id || t("defaultClient");
  const target = redirectTarget(consent.redirect_uri);
  const workspaces = consent.access === "mcp" ? await getWorkspaces() : [];
  const scopes = consent.scopes.filter((scope) =>
    (KNOWN_SCOPES as readonly string[]).includes(scope)
  ) as (typeof KNOWN_SCOPES)[number][];

  return (
    <ConsentCard
      title={t("title", { clientName })}
      description={t("description", { clientName })}
    >
      {target ? (
        <div
          className={
            target.loopback || consent.first_party
              ? "border-border/60 bg-muted/30 mb-5 rounded-lg border p-4"
              : "border-amber-500/40 bg-amber-500/5 mb-5 rounded-lg border p-4"
          }
        >
          <p className="text-foreground mb-1 text-xs font-medium uppercase tracking-wider">
            {t("redirectHeading")}
          </p>
          <p className="text-foreground break-all font-mono text-base font-semibold">
            {target.host}
          </p>
          <p className="text-muted-foreground mt-2 flex items-start gap-2 text-xs leading-relaxed">
            {!target.loopback && !consent.first_party && (
              <TriangleAlert className="mt-[1px] h-4 w-4 shrink-0 text-amber-600" />
            )}
            <span>
              {target.loopback
                ? t("redirectLoopback")
                : t("redirectUnverified", { clientName })}
            </span>
          </p>
        </div>
      ) : (
        <div className="text-destructive border-destructive/30 bg-destructive/5 mb-5 rounded-md border px-3 py-2 text-sm">
          {t("redirectUnknown")}
        </div>
      )}

      {consent.first_party && (
        <p className="text-muted-foreground mb-5 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 text-xs leading-relaxed">
          <TriangleAlert className="mt-[1px] h-4 w-4 shrink-0 text-amber-600" />
          <span>{t("firstPartyWarning")}</span>
        </p>
      )}

      <div className="border-border/60 bg-muted/30 mb-5 rounded-lg border p-4">
        <p className="text-foreground mb-3 text-xs font-medium uppercase tracking-wider">
          {t("permissionsHeading")}
        </p>
        <ul className="space-y-2.5">
          <li className="text-foreground flex items-start gap-2.5 text-sm font-medium leading-snug">
            <Check className="text-foreground/60 mt-[2px] h-4 w-4 shrink-0" />
            <span>
              {consent.access === "api" ? t("fullAccess") : t("mcpAccess")}
            </span>
          </li>
          {scopes.map((scope) => (
            <li
              key={scope}
              className="text-foreground/90 flex items-start gap-2.5 text-sm leading-snug"
            >
              <Check className="text-foreground/60 mt-[2px] h-4 w-4 shrink-0" />
              <span>{t(`scope.${scope}`)}</span>
            </li>
          ))}
        </ul>
      </div>

      <ConsentForm
        challenge={challenge}
        access={consent.access}
        workspaces={workspaces.map(({ slug, name }) => ({ slug, name }))}
        canAllow={target !== null}
      />

      <p className="text-muted-foreground mt-5 text-center text-xs leading-relaxed">
        {t("footnote")}
      </p>
    </ConsentCard>
  );
}

function ConsentCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <AuthLayout>
      <Card className="border-border bg-card text-card-foreground relative overflow-visible rounded-xl border p-8 shadow-sm">
        <div className="mb-7 flex justify-center">
          <Image
            src="/logo.svg"
            alt="AgentArea"
            width={180}
            height={48}
            priority
            className="h-12 w-auto"
          />
        </div>
        <div className="mb-6 text-center">
          <h1 className="text-foreground text-2xl font-semibold leading-tight tracking-tight">
            {title}
          </h1>
          {description && (
            <p className="text-muted-foreground mx-auto mt-3 max-w-sm text-sm leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {children}
      </Card>
    </AuthLayout>
  );
}

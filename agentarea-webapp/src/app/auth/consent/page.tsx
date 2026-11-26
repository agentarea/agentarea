import { getTranslations } from "next-intl/server";
import Image from "next/image";
import { ArrowLeftRight, Check } from "lucide-react";
import { AuthLayout } from "@/components/auth/auth-layout";
import EntityMark from "@/components/EntityMark";
import FormError from "@/components/FormError";
import Divider from "@/components/ui/divider";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getOAuthConsent } from "@/lib/api";
import {
  domainInitials,
  faviconSources,
  type EntityIdentity,
} from "@/lib/entity-identity";
import { getWorkspaces } from "@/lib/workspace-context";
import { ConsentForm } from "./ConsentForm";
import { ConsentLabel } from "./ConsentLabel";
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
        <FormError>
          {challenge ? t("error.loadFailed") : t("error.missingChallenge")}
        </FormError>
      </ConsentCard>
    );
  }

  const clientName =
    consent.client.client_name ||
    consent.client.client_id ||
    t("defaultClient");
  const target = redirectTarget(consent.redirect_uri);
  const workspaces = consent.access === "mcp" ? await getWorkspaces() : [];
  const scopes = consent.scopes.filter((scope) =>
    (KNOWN_SCOPES as readonly string[]).includes(scope)
  ) as (typeof KNOWN_SCOPES)[number][];
  const client: EntityIdentity = {
    kind: "client",
    sources: target?.loopback ? [] : faviconSources(consent.redirect_uri),
    initials: target?.loopback
      ? undefined
      : domainInitials(consent.redirect_uri, clientName),
  };

  // What the user should weigh before allowing: a name the client chose for
  // itself, or a first-party name any local app can claim.
  const caution = consent.first_party
    ? { label: t("firstPartyWarningTitle"), detail: t("firstPartyWarning") }
    : target && !target.loopback
      ? {
          label: t("redirectUnverifiedTitle"),
          detail: t("redirectUnverified", { clientName }),
        }
      : null;

  return (
    <ConsentCard
      client={client}
      title={t("title", { clientName })}
      description={t("description", { clientName })}
    >
      <div className="space-y-2">
        <ConsentLabel section="target">{t("redirectHeading")}</ConsentLabel>
        {target ? (
          <div className="card-item overflow-hidden pr-0">
            <div className="flex items-center gap-3 px-3 py-2.5">
              <EntityMark
                identity={client}
                className="h-5 w-5 shrink-0 rounded text-[9px]"
                glyphClassName="text-muted-foreground"
              />
              <span className="text-foreground min-w-0 flex-1 break-all font-mono text-sm font-semibold">
                {target.host}
              </span>
              {caution && (
                <StatusIndicator
                  kind="attention"
                  size="sm"
                  className="shrink-0"
                >
                  {caution.label}
                </StatusIndicator>
              )}
            </div>
            {(caution || target.loopback) && (
              <p className="border-border bg-muted/30 text-muted-foreground border-t px-3 py-2.5 text-xs leading-relaxed dark:border-zinc-700">
                {caution ? caution.detail : t("redirectLoopback")}
              </p>
            )}
          </div>
        ) : (
          <FormError>{t("redirectUnknown")}</FormError>
        )}
      </div>

      <Divider className="my-4" />

      <div className="space-y-3">
        <ConsentLabel section="permissions">
          {t("permissionsHeading")}
        </ConsentLabel>
        <ul className="space-y-2">
          <PermissionItem strong>
            {consent.access === "api" ? t("fullAccess") : t("mcpAccess")}
          </PermissionItem>
          {scopes.map((scope) => (
            <PermissionItem key={scope}>{t(`scope.${scope}`)}</PermissionItem>
          ))}
        </ul>
      </div>

      <Divider className="my-4" />

      <ConsentForm
        challenge={challenge}
        access={consent.access}
        workspaces={workspaces.map(({ id, slug, name, logo_url }) => ({
          id,
          slug,
          name,
          logo_url,
        }))}
        canAllow={target !== null}
      />

      <p className="note mt-4 text-center">{t("footnote")}</p>
    </ConsentCard>
  );
}

function PermissionItem({
  strong,
  children,
}: {
  strong?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="flex items-start gap-2.5 text-sm leading-snug">
      <Check className="text-primary dark:text-accent-foreground mt-[2px] h-4 w-4 shrink-0" />
      <span
        className={
          strong ? "text-foreground font-medium" : "text-foreground/80"
        }
      >
        {children}
      </span>
    </li>
  );
}

/** The client's mark joined to ours, the way the grant joins the two. */
function ConnectionMarks({ client }: { client: EntityIdentity }) {
  const tile =
    "card-shadow flex h-12 w-12 items-center justify-center rounded-xl border border-border bg-background dark:border-zinc-700 dark:bg-zinc-800";
  return (
    <div className="flex items-center justify-center gap-3" aria-hidden>
      <div className={tile}>
        <EntityMark
          identity={client}
          className="h-7 w-7 rounded-lg text-xs"
          glyphClassName="text-muted-foreground"
        />
      </div>
      <div className="flex items-center gap-1.5">
        <span className="bg-border h-1 w-1 rounded-full" />
        <span className="bg-border h-1 w-1 rounded-full" />
        <span className="bg-primary/10 dark:bg-accent flex h-6 w-6 items-center justify-center rounded-full">
          <ArrowLeftRight className="text-primary dark:text-accent-foreground h-3.5 w-3.5" />
        </span>
        <span className="bg-border h-1 w-1 rounded-full" />
        <span className="bg-border h-1 w-1 rounded-full" />
      </div>
      <div className={tile}>
        <Image
          src="/Icon.svg"
          alt=""
          width={32}
          height={32}
          className="h-7 w-7"
        />
      </div>
    </div>
  );
}

function ConsentCard({
  client,
  title,
  description,
  children,
}: {
  client?: EntityIdentity;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <AuthLayout>
      <section className="auth-card bg-background border border-slate-300 p-6 sm:p-8 dark:border-zinc-700">
        <div className="mb-4 flex justify-center">
          {client ? (
            <ConnectionMarks client={client} />
          ) : (
            <Image
              src="/logo.svg"
              alt="AgentArea"
              width={180}
              height={48}
              priority
              className="h-12 w-auto"
            />
          )}
        </div>
        <div className="mb-5 text-center">
          <h1 className="text-foreground text-2xl font-semibold leading-tight tracking-tight">
            {title}
          </h1>
          {description && (
            <p className="text-muted-foreground mx-auto mt-2 max-w-sm text-sm leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {children}
      </section>
    </AuthLayout>
  );
}

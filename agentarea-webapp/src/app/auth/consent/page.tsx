"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AuthLayout } from "@/components/auth/auth-layout";

const KNOWN_SCOPES = ["openid", "profile", "email", "offline_access"] as const;

interface ConsentRequest {
  client?: { client_name?: string; client_id?: string };
  requested_scope?: string[];
  requested_access_token_audience?: string[];
  subject?: string;
}

export default function ConsentPage() {
  const t = useTranslations("AuthConsent");
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [consentRequest, setConsentRequest] = useState<ConsentRequest | null>(null);
  const searchParams = useSearchParams();
  const consentChallenge = searchParams.get("consent_challenge");

  useEffect(() => {
    if (!consentChallenge) {
      setError(t("error.missingChallenge"));
      setLoading(false);
      return;
    }

    fetch(`/api/hydra/consent?challenge=${consentChallenge}`)
      .then((response) => response.json())
      .then((data) => {
        setConsentRequest(data);
        setLoading(false);
      })
      .catch(() => {
        setError(t("error.loadFailed"));
        setLoading(false);
      });
  }, [consentChallenge, t]);

  const handleAccept = async () => {
    if (!consentChallenge) return;

    setSubmitting(true);
    try {
      const response = await fetch(
        `/api/hydra/consent?challenge=${consentChallenge}&action=accept`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            grant_scope: consentRequest?.requested_scope || [
              "openid",
              "profile",
              "email",
            ],
            grant_access_token_audience:
              consentRequest?.requested_access_token_audience || [],
            session: {
              id_token: {
                email: consentRequest?.subject || "",
                name: "Ory User",
              },
            },
          }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_to;
      } else {
        setError(t("error.acceptFailed"));
        setSubmitting(false);
      }
    } catch {
      setError(t("error.acceptFailed"));
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!consentChallenge) return;

    setSubmitting(true);
    try {
      const response = await fetch(
        `/api/hydra/consent?challenge=${consentChallenge}&action=reject`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            error: "access_denied",
            error_description: "The user denied the request",
          }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_to;
      } else {
        setError(t("error.rejectFailed"));
        setSubmitting(false);
      }
    } catch {
      setError(t("error.rejectFailed"));
      setSubmitting(false);
    }
  };

  const clientName =
    consentRequest?.client?.client_name ||
    consentRequest?.client?.client_id ||
    t("defaultClient");

  const scopes: string[] = consentRequest?.requested_scope || [];

  const scopeLabel = (scope: string) =>
    (KNOWN_SCOPES as readonly string[]).includes(scope)
      ? t(`scope.${scope}` as `scope.${(typeof KNOWN_SCOPES)[number]}`)
      : scope;

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
            {t("title", { clientName })}
          </h1>
          <p className="text-muted-foreground mx-auto mt-3 max-w-sm text-sm leading-relaxed">
            {t("description", { clientName })}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div
              className="border-muted-foreground/30 border-t-foreground inline-block h-5 w-5 animate-spin rounded-full border-2"
              role="status"
              aria-label="Loading"
            />
          </div>
        ) : (
          <>
            {error && (
              <div className="text-destructive border-destructive/30 bg-destructive/5 mb-5 rounded-md border px-3 py-2 text-sm">
                {error}
              </div>
            )}

            {scopes.length > 0 && (
              <div className="border-border/60 bg-muted/30 mb-5 rounded-lg border p-4">
                <p className="text-foreground mb-3 text-xs font-medium uppercase tracking-wider">
                  {t("permissionsHeading")}
                </p>
                <ul className="space-y-2.5">
                  {scopes.map((scope) => (
                    <li
                      key={scope}
                      className="text-foreground/90 flex items-start gap-2.5 text-sm leading-snug"
                    >
                      <Check className="text-foreground/60 mt-[2px] h-4 w-4 shrink-0" />
                      <span>{scopeLabel(scope)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-col gap-2">
              <Button
                onClick={handleAccept}
                disabled={submitting || !!error}
                className="h-11 w-full rounded-md bg-[#2252b3] text-sm font-medium text-white shadow-sm hover:bg-[#1a3f8a]"
              >
                {t("allow")}
              </Button>
              <Button
                onClick={handleReject}
                variant="outline"
                disabled={submitting}
                className="h-11 w-full rounded-md text-sm font-medium"
              >
                {t("deny")}
              </Button>
            </div>

            <p className="text-muted-foreground mt-5 text-center text-xs leading-relaxed">
              {t("footnote")}
            </p>
          </>
        )}
      </Card>
    </AuthLayout>
  );
}

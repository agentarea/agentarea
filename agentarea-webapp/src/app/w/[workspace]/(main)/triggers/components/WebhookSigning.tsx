"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { KeyRound, ShieldCheck } from "lucide-react";
import type { WebhookSignatureScheme } from "@/api/client/types.gen";
import BaseModal from "@/components/BaseModal/BaseModal";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  OneTimeSecretField,
  SuccessModalContent,
  SuccessModalDetail,
} from "@/components/SuccessModal";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { rotateSigningSecretAction } from "../[id]/actions";

/** A sender's whole job, as a shell snippet: sign the exact body, send it. */
function signingExample(scheme: WebhookSignatureScheme): string {
  return [
    `BODY='{"text":"hello"}'`,
    `SIG=$(printf '%s' "$BODY" | openssl dgst -${scheme.algorithm} -hmac "$SECRET" | sed 's/^.*= //')`,
    `curl -X POST "$WEBHOOK_URL" \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  -H "${scheme.header}: ${scheme.prefix}$SIG" \\`,
    `  --data "$BODY"`,
  ].join("\n");
}

/**
 * The generated signing secret of a generic webhook, shown once, with what a
 * sender has to do with it. Used right after creating the webhook and after
 * rotating its secret.
 */
export function SigningSecretIssuedDialog({
  title,
  secret,
  scheme,
  onDone,
}: {
  title: string;
  secret: string;
  scheme: WebhookSignatureScheme;
  onDone: () => void;
}) {
  const t = useTranslations("TriggersPage.signing");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onDone();
      }}
    >
      <SuccessModalContent
        title={title}
        description={t("issuedDescription")}
        doneLabel={t("done")}
        onDone={onDone}
      >
        <OneTimeSecretField
          label={t("secretLabel")}
          icon={KeyRound}
          value={secret}
          warning={t("secretWarning")}
        />
        <SuccessModalDetail label={t("headerLabel")}>
          <code className="font-mono text-[12px] text-foreground">
            {scheme.header}
          </code>
        </SuccessModalDetail>
        <SuccessModalDetail label={t("valueLabel")}>
          {scheme.prefix
            ? t("valueTextWithPrefix", {
                algorithm: scheme.algorithm.toUpperCase(),
                prefix: scheme.prefix,
              })
            : t("valueText", { algorithm: scheme.algorithm.toUpperCase() })}
        </SuccessModalDetail>
        <div className="min-w-0 space-y-2">
          <FormLabel>{t("exampleLabel")}</FormLabel>
          <pre className="max-h-48 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-[11px] leading-relaxed">
            {signingExample(scheme)}
          </pre>
        </div>
      </SuccessModalContent>
    </Dialog>
  );
}

/**
 * Generate (unsigned webhook) or rotate (signed one) the signing secret.
 * Either way the senders must change, so the action asks first.
 */
export function WebhookSigningControl({
  triggerId,
  signed,
}: {
  triggerId: string;
  signed: boolean;
}) {
  const t = useTranslations("TriggersPage.signing");
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<{
    secret: string;
    scheme: WebhookSignatureScheme;
  } | null>(null);

  const handleConfirm = async () => {
    setError(null);
    const result = await rotateSigningSecretAction(triggerId);
    if (!result.success) {
      setError(result.error);
      return false;
    }
    setIssued({ secret: result.signingSecret, scheme: result.scheme });
  };

  return (
    <>
      <BaseModal
        type="confirm"
        title={signed ? t("rotateTitle") : t("signTitle")}
        description={signed ? t("rotateDescription") : t("signDescription")}
        confirmLabel={signed ? t("rotateConfirm") : t("signConfirm")}
        error={error}
        onConfirm={handleConfirm}
        onOpenChange={(open) => {
          if (open) setError(null);
        }}
      >
        <Button type="button" variant="outline" size="xs">
          <ShieldCheck />
          {signed ? t("rotate") : t("sign")}
        </Button>
      </BaseModal>
      {issued && (
        <SigningSecretIssuedDialog
          title={t("issuedTitle")}
          secret={issued.secret}
          scheme={issued.scheme}
          onDone={() => {
            setIssued(null);
            router.refresh();
          }}
        />
      )}
    </>
  );
}

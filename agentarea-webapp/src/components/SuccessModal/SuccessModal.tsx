"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { TriangleAlert, type LucideIcon } from "lucide-react";
import { ModalFeaturedIcon } from "@/components/BaseModal/ModalFeaturedIcon";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SuccessModalContentProps {
  title: ReactNode;
  description: ReactNode;
  /** Body under the header — usually a {@link OneTimeSecretField} and {@link SuccessModalDetail}s. */
  children?: ReactNode;
  doneLabel: ReactNode;
  onDone: () => void;
}

/**
 * "Created" step of a create dialog: check icon with rings, title, body and a
 * single Done button. Goes inside a `<Dialog>`, in place of the form content.
 */
export function SuccessModalContent({
  title,
  description,
  children,
  doneLabel,
  onDone,
}: SuccessModalContentProps) {
  return (
    <DialogContent className="w-[calc(100vw-2rem)] max-w-[480px] overflow-hidden">
      <ModalFeaturedIcon type="success" />
      <DialogHeader className="relative z-10 mt-3">
        <DialogTitle className="pb-2">{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>
      {children ? (
        <div className="relative z-10 min-w-0 space-y-4">{children}</div>
      ) : null}
      <DialogFooter className="relative z-10">
        <Button size="sm" onClick={onDone}>
          {doneLabel}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

interface OneTimeSecretFieldProps {
  label: ReactNode;
  icon?: LucideIcon;
  /** The value that can't be shown again once the dialog closes. */
  value: string;
  /** "Copy it now" line under the value. */
  warning: ReactNode;
  onCopied?: () => void;
}

/** A value shown once: label, click-to-copy box and the "copy it now" warning. */
export function OneTimeSecretField({
  label,
  icon,
  value,
  warning,
  onCopied,
}: OneTimeSecretFieldProps) {
  const t = useTranslations("Common");
  const [copyFailed, setCopyFailed] = useState(false);

  return (
    <div className="min-w-0 space-y-2">
      <FormLabel icon={icon}>{label}</FormLabel>
      <CopyableText
        text={value}
        onCopied={() => {
          setCopyFailed(false);
          onCopied?.();
        }}
        onCopyError={() => setCopyFailed(true)}
      />
      {copyFailed && (
        <p className="text-xs text-destructive" role="alert">
          {t("copyFailed")}
        </p>
      )}
      <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
        <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
        <span>{warning}</span>
      </p>
    </div>
  );
}

/** A labelled read-only fact under the secret (expiry date, scope…). */
export function SuccessModalDetail({
  label,
  icon,
  children,
}: {
  label: ReactNode;
  icon?: LucideIcon;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <FormLabel icon={icon}>{label}</FormLabel>
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

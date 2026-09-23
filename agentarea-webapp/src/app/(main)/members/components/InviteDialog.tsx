"use client";

import { useState, useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Clock, Link2, Loader2, Mail, UserPlus } from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  OneTimeSecretField,
  SuccessModalContent,
  SuccessModalDetail,
} from "@/components/SuccessModal";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WorkspaceInvitationCreated } from "@/lib/api";
import { formatDate } from "@/utils/dateUtils";
import { createInvitationAction } from "../actions";

interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called once an invitation has been created (e.g. to switch to the list). */
  onCreated?: () => void;
}

const EXPIRY_OPTIONS = ["7", "14", "30"] as const;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Header "Invite people" button — opens {@link InviteDialog}. */
export function InviteButton({ onClick }: { onClick: () => void }) {
  const t = useTranslations("MembersPage");
  return (
    <Button size="sm" onClick={onClick}>
      <UserPlus />
      {t("invitePeople")}
    </Button>
  );
}

export function InviteDialog({
  open,
  onOpenChange,
  onCreated,
}: InviteDialogProps) {
  const t = useTranslations("MembersPage");
  const locale = useLocale();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const [email, setEmail] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<string>("7");
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{
    link: string;
    invitation: WorkspaceInvitationCreated;
  } | null>(null);
  const [hasCopied, setHasCopied] = useState(false);
  const [closeWarning, setCloseWarning] = useState(false);

  const handleOpenChange = (next: boolean) => {
    if (!next && created && !hasCopied) {
      setCloseWarning(true);
      return;
    }
    onOpenChange(next);
  };

  const handleCreate = () => {
    const recipient = email.trim();
    if (recipient && !EMAIL_PATTERN.test(recipient)) {
      setError(t("emailInvalid"));
      return;
    }
    setError(null);
    startTransition(async () => {
      const res = await createInvitationAction({
        email: recipient || undefined,
        expiresInDays: Number(expiresInDays),
      });
      if (res.error || !res.data) {
        setError(res.error || t("createFailed"));
        return;
      }
      const token = res.data.token;
      const link = token
        ? `${window.location.origin}/invite?token=${encodeURIComponent(token)}`
        : "";
      setCreated({ link, invitation: res.data });
      toast.success(t("inviteLinkCreatedTitle"));
      router.refresh();
      onCreated?.();
    });
  };

  if (created) {
    const { invitation } = created;
    return (
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <SuccessModalContent
          title={t("inviteLinkCreatedTitle")}
          description={
            invitation.email
              ? t("inviteLinkOnlyEmail", { email: invitation.email })
              : t("inviteLinkAnyone")
          }
          doneLabel={t("done")}
          onDone={() => onOpenChange(false)}
        >
          {invitation.email_delivery === "sent" && invitation.email && (
            <p className="text-xs text-muted-foreground">
              {t("emailSent", { email: invitation.email })}
            </p>
          )}
          {(invitation.email_delivery === "not_configured" ||
            invitation.email_delivery === "failed") && (
            <p className="text-xs text-destructive" role="alert">
              {invitation.email_delivery === "not_configured"
                ? t("emailNotConfigured")
                : t("emailFailed")}
            </p>
          )}
          <OneTimeSecretField
            label={t("invitationLinkLabel")}
            icon={Link2}
            value={created.link}
            warning={t("shownOnce")}
            onCopied={() => {
              setHasCopied(true);
              setCloseWarning(false);
            }}
          />
          {closeWarning && (
            <p className="text-xs text-destructive" role="alert">
              {t("closeWarning")}
            </p>
          )}
          <SuccessModalDetail label={t("expiresLabel")} icon={Clock}>
            {formatDate(invitation.expires_at, locale)}
          </SuccessModalDetail>
        </SuccessModalContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <BlueprintDialogContent
        title={t("inviteDialogTitle")}
        description={t("inviteDialogDescription")}
        note={t("joinsAsMember")}
        actions={
          <Button size="sm" onClick={handleCreate} disabled={isPending}>
            {isPending && <Loader2 className="animate-spin" />}
            {t("createInvite")}
          </Button>
        }
      >
        <BlueprintFields>
          <div className="space-y-2">
            <FormLabel htmlFor="invite-email" icon={Mail} optional>
              {t("emailLabel")}
            </FormLabel>
            <Input
              id="invite-email"
              type="email"
              autoComplete="off"
              placeholder={t("emailPlaceholder")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <p className="note">{t("emailHint")}</p>
          </div>
          <div className="space-y-2">
            <FormLabel htmlFor="invite-expiry" icon={Clock}>
              {t("expiryLabel")}
            </FormLabel>
            <Select value={expiresInDays} onValueChange={setExpiresInDays}>
              <SelectTrigger id="invite-expiry" className="text-[13px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXPIRY_OPTIONS.map((days) => (
                  <SelectItem key={days} value={days} className="text-[13px]">
                    {t(`expiry${days}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </BlueprintFields>
      </BlueprintDialogContent>
    </Dialog>
  );
}

"use client";

import { useState, useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  Clock,
  Link2,
  Loader2,
  Mail,
  TriangleAlert,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  BlueprintDivider,
  BlueprintSheet,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { WorkspaceInvitationCreated } from "@/lib/api";
import { createInvitationAction } from "../actions";
import { formatDate } from "./membersShared";

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
  const [copyFailed, setCopyFailed] = useState(false);
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

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="min-w-0 max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-[496px] sm:rounded-[10px]">
        <DialogHeader className="space-y-1.5 px-6 pb-4 pt-5">
          <DialogTitle>
            {created ? t("inviteLinkCreatedTitle") : t("inviteDialogTitle")}
          </DialogTitle>
          <DialogDescription>
            {created
              ? created.invitation.email
                ? t("inviteLinkOnlyEmail", { email: created.invitation.email })
                : t("inviteLinkAnyone")
              : t("inviteDialogDescription")}
          </DialogDescription>
        </DialogHeader>

        <BlueprintSheet className="min-w-0" style={{ paddingBottom: 0 }}>
          <BlueprintDivider />
          <div className="relative z-[1] min-w-0 space-y-5 px-4 py-5">
            {created ? (
              <>
                <div className="space-y-2">
                  {created.invitation.email_delivery === "sent" &&
                    created.invitation.email && (
                      <p className="text-xs text-muted-foreground">
                        {t("emailSent", { email: created.invitation.email })}
                      </p>
                    )}
                  {(created.invitation.email_delivery === "not_configured" ||
                    created.invitation.email_delivery === "failed") && (
                    <p className="text-xs text-destructive" role="alert">
                      {created.invitation.email_delivery === "not_configured"
                        ? t("emailNotConfigured")
                        : t("emailFailed")}
                    </p>
                  )}
                  <FormLabel icon={Link2}>{t("invitationLinkLabel")}</FormLabel>
                  <CopyableText
                    text={created.link}
                    onCopied={() => {
                      setHasCopied(true);
                      setCopyFailed(false);
                      setCloseWarning(false);
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
                    <span>{t("shownOnce")}</span>
                  </p>
                  {closeWarning && (
                    <p className="text-xs text-destructive" role="alert">
                      {t("closeWarning")}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <FormLabel icon={Clock}>{t("expiresLabel")}</FormLabel>
                  <p className="text-sm text-muted-foreground">
                    {formatDate(created.invitation.expires_at, locale)}
                  </p>
                </div>
              </>
            ) : (
              <>
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
                  <Select
                    value={expiresInDays}
                    onValueChange={setExpiresInDays}
                  >
                    <SelectTrigger id="invite-expiry" className="text-[13px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EXPIRY_OPTIONS.map((days) => (
                        <SelectItem
                          key={days}
                          value={days}
                          className="text-[13px]"
                        >
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
              </>
            )}
          </div>
          <BlueprintDivider />
        </BlueprintSheet>

        <DialogFooter className="px-6 py-4 sm:items-center sm:justify-between">
          {created ? (
            <>
              <span />
              <Button size="sm" onClick={() => onOpenChange(false)}>
                {t("done")}
              </Button>
            </>
          ) : (
            <>
              <p className="note text-left">{t("joinsAsMember")}</p>
              <Button size="sm" onClick={handleCreate} disabled={isPending}>
                {isPending && <Loader2 className="animate-spin" />}
                {t("createInvite")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

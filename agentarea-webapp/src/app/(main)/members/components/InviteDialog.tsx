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
import { Label } from "@/components/ui/label";
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

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setEmail("");
      setExpiresInDays("7");
      setError(null);
      setCreated(null);
    }
    onOpenChange(next);
  };

  const handleCreate = () => {
    setError(null);
    startTransition(async () => {
      const res = await createInvitationAction({
        email: email || undefined,
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
      <DialogContent className="max-w-[468px]">
        <DialogHeader>
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

        {created ? (
          <div className="space-y-5">
            <div className="space-y-1.5">
              <Label className="label">
                <Link2 className="label-icon" />
                {t("invitationLinkLabel")}
              </Label>
              <CopyableText text={created.link} labelClassName="text-xs" />
              <p className="flex items-start gap-1.5 text-xs text-amber-600 dark:text-amber-400">
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                <span>{t("shownOnce")}</span>
              </p>
            </div>
            <div className="space-y-1.5">
              <Label className="label">
                <Clock className="label-icon" />
                {t("expiresLabel")}
              </Label>
              <p className="text-sm text-muted-foreground">
                {formatDate(created.invitation.expires_at, locale)}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-5">
            <div className="space-y-1.5">
              <Label htmlFor="invite-email" className="label">
                <Mail className="label-icon" />
                {t("emailLabel")}
              </Label>
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
            <div className="space-y-1.5">
              <Label className="label">
                <Clock className="label-icon" />
                {t("expiryLabel")}
              </Label>
              <Select value={expiresInDays} onValueChange={setExpiresInDays}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPIRY_OPTIONS.map((days) => (
                    <SelectItem key={days} value={days}>
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
          </div>
        )}

        <DialogFooter className="sm:items-center sm:justify-between">
          {created ? (
            <>
              <span />
              <Button onClick={() => onOpenChange(false)}>{t("done")}</Button>
            </>
          ) : (
            <>
              <p className="note text-left">{t("joinsAsMember")}</p>
              <Button onClick={handleCreate} disabled={isPending}>
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

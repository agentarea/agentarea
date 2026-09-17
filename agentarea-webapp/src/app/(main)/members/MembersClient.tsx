"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import {
  Check,
  Copy,
  Link2,
  Loader2,
  LogOut,
  Mail,
  MoreHorizontal,
  Trash2,
  UserPlus,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { WorkspaceInvitation, WorkspaceMember } from "@/lib/api";
import {
  createInvitationAction,
  removeMemberAction,
  revokeInvitationAction,
} from "./actions";

interface MembersClientProps {
  members: WorkspaceMember[];
  invitations: WorkspaceInvitation[];
  currentUserId: string | null;
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function shortenId(userId: string): string {
  return userId.length > 12 ? `${userId.slice(0, 8)}…` : userId;
}

function initials(label: string): string {
  // For an email only the local part carries a name; the domain would turn
  // alice@example.com into "AE".
  const base = label.includes("@") ? label.slice(0, label.indexOf("@")) : label;
  const parts = base.trim().split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default function MembersClient({
  members,
  invitations,
  currentUserId,
}: MembersClientProps) {
  const t = useTranslations("MembersPage");
  const format = useFormatter();
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("7");
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [createdLink, setCreatedLink] = useState<string | null>(null);
  // `copied` drives the transient check icon and resets itself; `hasCopied`
  // records that the link was taken at all and must not expire, or closing the
  // dialog a few seconds later would warn about a link already in hand.
  const [copied, setCopied] = useState(false);
  const [hasCopied, setHasCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [closeWarning, setCloseWarning] = useState(false);
  const [emailDelivery, setEmailDelivery] = useState<string | null>(null);

  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<WorkspaceMember | null>(
    null
  );

  const ownerId = members.find((m) => m.is_owner)?.user_id ?? null;
  const viewerIsOwner = ownerId !== null && ownerId === currentUserId;

  const formatDate = (value?: string | null): string => {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return format.dateTime(date, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const memberLabel = (member: WorkspaceMember) =>
    member.display_name || member.email || null;

  const openInvite = () => {
    setEmail("");
    setExpiresInDays("7");
    setInviteError(null);
    setCreatedLink(null);
    setCopied(false);
    setHasCopied(false);
    setCopyFailed(false);
    setCloseWarning(false);
    setEmailDelivery(null);
    setInviteOpen(true);
  };

  const handleCreate = () => {
    if (email.trim() && !EMAIL_PATTERN.test(email.trim())) {
      setInviteError(t("emailInvalid"));
      return;
    }
    setInviteError(null);
    startTransition(async () => {
      const res = await createInvitationAction({
        email: email.trim() || undefined,
        expiresInDays: Number(expiresInDays),
      });
      if (res.error || !res.data) {
        setInviteError(res.error || t("createFailed"));
        return;
      }
      const created = res.data as {
        token?: string;
        email_delivery?: string;
      };
      setCreatedLink(
        created.token
          ? `${window.location.origin}/invite?token=${encodeURIComponent(created.token)}`
          : ""
      );
      setEmailDelivery(created.email_delivery ?? null);
      router.refresh();
    });
  };

  const handleCopy = async () => {
    if (!createdLink) return;
    try {
      await navigator.clipboard.writeText(createdLink);
      setCopied(true);
      setHasCopied(true);
      setCopyFailed(false);
      setCloseWarning(false);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access is denied outside secure contexts; the link is still
      // on screen, so point the user at selecting it by hand.
      setCopyFailed(true);
    }
  };

  const handleInviteOpenChange = (open: boolean) => {
    if (!open && createdLink && !hasCopied) {
      setCloseWarning(true);
      return;
    }
    setInviteOpen(open);
  };

  const handleRevoke = (invitationId: string) => {
    setActionError(null);
    startTransition(async () => {
      const res = await revokeInvitationAction(invitationId);
      if (res.error) {
        setActionError(res.error);
        return;
      }
      router.refresh();
    });
  };

  const confirmRemoval = () => {
    const member = pendingRemoval;
    if (!member) return;
    const isSelf = member.user_id === currentUserId;
    setActionError(null);
    startTransition(async () => {
      const res = await removeMemberAction(member.user_id);
      setPendingRemoval(null);
      if (res.error) {
        setActionError(res.error);
        return;
      }
      // Leaving removes the caller's own access to this page.
      if (isSelf) {
        router.push("/");
        return;
      }
      router.refresh();
    });
  };

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-medium">
              {t("membersTitle")} ({members.length})
            </h2>
            <p className="text-sm text-muted-foreground">
              {t("membersDescription")}
            </p>
          </div>
          <Button size="sm" className="gap-1.5" onClick={openInvite}>
            <UserPlus />
            {t("invitePeople")}
          </Button>
        </div>

        {actionError && (
          <p className="text-sm text-destructive" role="alert">
            {actionError}
          </p>
        )}

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("member")}</TableHead>
              <TableHead>{t("joined")}</TableHead>
              <TableHead className="w-0">
                <span className="sr-only">{t("actions")}</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((member) => {
              const isSelf = member.user_id === currentUserId;
              const label = memberLabel(member);
              const secondary =
                label && member.email && member.email !== label
                  ? member.email
                  : null;
              const canLeave = isSelf && !member.is_owner;
              const canRemove = viewerIsOwner && !isSelf && !member.is_owner;

              return (
                <TableRow key={member.id}>
                  <TableCell>
                    <span className="flex min-w-0 items-center gap-2.5">
                      <EntityAvatar
                        size={28}
                        text={initials(label ?? member.user_id)}
                        variant="soft"
                      />
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className={
                              label
                                ? "truncate font-medium"
                                : "truncate font-medium text-muted-foreground"
                            }
                          >
                            {label ?? t("unknownMember")}
                          </span>
                          {isSelf && (
                            <Badge variant="secondary">{t("you")}</Badge>
                          )}
                          {member.is_owner && (
                            <Badge variant="outline">{t("owner")}</Badge>
                          )}
                        </span>
                        <span className="truncate text-xs text-muted-foreground">
                          {secondary ?? shortenId(member.user_id)}
                        </span>
                      </span>
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDate(member.joined_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    {(canLeave || canRemove) && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="sm"
                            disabled={isPending}
                            aria-label={t("memberActions", {
                              member: label ?? member.user_id,
                            })}
                          >
                            {isPending ? (
                              <Loader2 className="animate-spin" />
                            ) : (
                              <MoreHorizontal />
                            )}
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            className="text-destructive"
                            onSelect={() => setPendingRemoval(member)}
                          >
                            {canLeave ? <LogOut /> : <Trash2 />}
                            <span className="ml-2">
                              {canLeave ? t("leave") : t("remove")}
                            </span>
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </section>

      <section className="space-y-3">
        {invitations.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noInvitations")}</p>
        ) : (
          <>
            <div>
              <h2 className="text-sm font-medium">
                {t("invitationsTitle")} ({invitations.length})
              </h2>
              <p className="text-sm text-muted-foreground">
                {t("invitationsDescription")}
              </p>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("recipient")}</TableHead>
                  <TableHead>{t("invitedBy")}</TableHead>
                  <TableHead>{t("expires")}</TableHead>
                  <TableHead className="w-0">
                    <span className="sr-only">{t("actions")}</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.map((invitation) => {
                  const expired = new Date(invitation.expires_at) < new Date();
                  return (
                    <TableRow
                      key={invitation.id}
                      className={expired ? "opacity-60" : undefined}
                    >
                      <TableCell>
                        <span className="flex items-center gap-2">
                          {invitation.email ? (
                            <>
                              <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                              {invitation.email}
                            </>
                          ) : (
                            <>
                              <Link2 className="h-3.5 w-3.5 text-muted-foreground" />
                              <span className="text-muted-foreground">
                                {t("anyoneWithLink")}
                              </span>
                            </>
                          )}
                        </span>
                      </TableCell>
                      <TableCell>
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="truncate">
                            {invitation.invited_by_display_name ??
                              shortenId(invitation.invited_by)}
                          </span>
                          <span className="truncate text-xs text-muted-foreground">
                            {formatDate(invitation.created_at)}
                          </span>
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <span className="flex items-center gap-2">
                          {formatDate(invitation.expires_at)}
                          {expired && (
                            <Badge variant="destructive">{t("expired")}</Badge>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground hover:text-destructive"
                          disabled={isPending}
                          onClick={() => handleRevoke(invitation.id)}
                        >
                          {isPending ? (
                            <Loader2 className="animate-spin" />
                          ) : (
                            <Trash2 />
                          )}
                          <span className="ml-1">{t("revoke")}</span>
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </>
        )}
      </section>

      <Dialog
        open={pendingRemoval !== null}
        onOpenChange={(open) => !open && setPendingRemoval(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {pendingRemoval?.user_id === currentUserId
                ? t("leaveConfirmTitle")
                : t("removeConfirmTitle")}
            </DialogTitle>
            <DialogDescription>
              {pendingRemoval?.user_id === currentUserId
                ? t("leaveConfirmDescription")
                : t("removeConfirmDescription", {
                    member:
                      (pendingRemoval && memberLabel(pendingRemoval)) ??
                      (pendingRemoval ? shortenId(pendingRemoval.user_id) : ""),
                  })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingRemoval(null)}
              disabled={isPending}
            >
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={confirmRemoval}
              disabled={isPending}
            >
              {isPending && <Loader2 className="mr-2 animate-spin" />}
              {pendingRemoval?.user_id === currentUserId
                ? t("leave")
                : t("remove")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={inviteOpen} onOpenChange={handleInviteOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("inviteDialogTitle")}</DialogTitle>
            <DialogDescription>{t("inviteDialogDescription")}</DialogDescription>
          </DialogHeader>

          {createdLink ? (
            <>
              <div className="space-y-3">
                {emailDelivery === "sent" ? (
                  <p className="text-sm text-muted-foreground">
                    {t("emailSent", { email: email.trim() })}
                  </p>
                ) : (
                  emailDelivery !== null &&
                  emailDelivery !== "not_requested" && (
                    <p className="text-sm text-destructive" role="alert">
                      {emailDelivery === "not_configured"
                        ? t("emailNotConfigured")
                        : t("emailFailed")}
                    </p>
                  )
                )}
                <p className="text-sm text-muted-foreground">
                  {t("inviteLinkHint")}
                </p>
                <div className="flex items-center gap-2">
                  <Input
                    readOnly
                    value={createdLink}
                    className="font-mono text-xs"
                    onFocus={(e) => e.currentTarget.select()}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    onClick={handleCopy}
                    aria-label={t("copyLink")}
                  >
                    {copied ? <Check className="text-green-600" /> : <Copy />}
                  </Button>
                </div>
                {copyFailed && (
                  <p className="text-sm text-destructive">{t("copyFailed")}</p>
                )}
                {closeWarning && (
                  <p className="text-sm text-destructive" role="alert">
                    {t("closeWarning")}
                  </p>
                )}
              </div>
              <DialogFooter>
                <Button onClick={() => setInviteOpen(false)}>{t("done")}</Button>
              </DialogFooter>
            </>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleCreate();
              }}
            >
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="invite-email">{t("emailLabel")}</Label>
                  <Input
                    id="invite-email"
                    type="email"
                    placeholder={t("emailPlaceholder")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("emailHint")}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("expiryLabel")}</Label>
                  <Select
                    value={expiresInDays}
                    onValueChange={setExpiresInDays}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="7">{t("expiry7")}</SelectItem>
                      <SelectItem value="14">{t("expiry14")}</SelectItem>
                      <SelectItem value="30">{t("expiry30")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {inviteError && (
                  <p className="text-sm text-destructive" role="alert">
                    {inviteError}
                  </p>
                )}
              </div>
              <DialogFooter className="mt-6">
                <Button type="submit" disabled={isPending}>
                  {isPending && <Loader2 className="mr-2 animate-spin" />}
                  {t("createInvite")}
                </Button>
              </DialogFooter>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

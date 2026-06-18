"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  Check,
  Copy,
  Link2,
  Loader2,
  Mail,
  Trash2,
  UserPlus,
  Users,
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
import { EmptyState } from "@/components/ui/empty-state";
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

type DisplayMember = WorkspaceMember & {
  email?: string | null;
  display_name?: string | null;
  name?: string | null;
  username?: string | null;
};

interface MembersClientProps {
  members: DisplayMember[];
  invitations: WorkspaceInvitation[];
  currentUserId: string | null;
  currentUserEmail: string | null;
  currentUserName: string | null;
  currentUsername: string | null;
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function getMemberLabel(
  member: DisplayMember,
  currentUser: {
    id: string | null;
    email: string | null;
    name: string | null;
    username: string | null;
  }
): string {
  const isSelf = member.user_id === currentUser.id;
  return (
    member.display_name ||
    member.email ||
    member.name ||
    member.username ||
    (isSelf && (currentUser.name || currentUser.email || currentUser.username)) ||
    member.user_id
  );
}

function getMemberSecondaryLabel(
  member: DisplayMember,
  currentUser: {
    id: string | null;
    email: string | null;
    name: string | null;
    username: string | null;
  }
): string | null {
  const label = getMemberLabel(member, currentUser);
  const isSelf = member.user_id === currentUser.id;
  if (member.email && member.email !== label) return member.email;
  if (member.username && member.username !== label) return member.username;
  if (isSelf && currentUser.email && currentUser.email !== label) {
    return currentUser.email;
  }
  if (isSelf && currentUser.username && currentUser.username !== label) {
    return currentUser.username;
  }
  return null;
}

export default function MembersClient({
  members,
  invitations,
  currentUserId,
  currentUserEmail,
  currentUserName,
  currentUsername,
}: MembersClientProps) {
  const t = useTranslations("MembersPage");
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  const [inviteOpen, setInviteOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("7");
  const [error, setError] = useState<string | null>(null);
  const [createdLink, setCreatedLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const openInvite = () => {
    setEmail("");
    setExpiresInDays("7");
    setError(null);
    setCreatedLink(null);
    setCopied(false);
    setInviteOpen(true);
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
      const token = (res.data as { token?: string }).token;
      const link = token
        ? `${window.location.origin}/invite?token=${encodeURIComponent(token)}`
        : "";
      setCreatedLink(link);
      router.refresh();
    });
  };

  const handleCopy = async () => {
    if (!createdLink) return;
    await navigator.clipboard.writeText(createdLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRevoke = (invitationId: string) => {
    setBusyId(invitationId);
    startTransition(async () => {
      const res = await revokeInvitationAction(invitationId);
      setBusyId(null);
      if (!res.error) router.refresh();
    });
  };

  const handleRemove = (userId: string) => {
    if (!window.confirm(t("removeConfirm"))) return;
    setBusyId(userId);
    startTransition(async () => {
      const res = await removeMemberAction(userId);
      setBusyId(null);
      if (!res.error) router.refresh();
    });
  };

  return (
    <div className="space-y-8">
      {/* Members */}
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
            <UserPlus className="h-4 w-4" />
            {t("invitePeople")}
          </Button>
        </div>
        {members.length === 0 ? (
            <div className="flex justify-center py-6">
              <EmptyState
                icons={[Users]}
                title={t("noMembersTitle")}
                description={t("noMembersDescription")}
                action={{ label: t("invitePeople"), onClick: openInvite }}
              />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("member")}</TableHead>
                  <TableHead>{t("joined")}</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => {
                  const isSelf = m.user_id === currentUserId;
                  const currentUser = {
                    id: currentUserId,
                    email: currentUserEmail,
                    name: currentUserName,
                    username: currentUsername,
                  };
                  const label = getMemberLabel(m, currentUser);
                  const secondaryLabel = getMemberSecondaryLabel(m, currentUser);
                  return (
                    <TableRow key={m.id}>
                      <TableCell>
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-medium">
                              {label}
                            </span>
                            {isSelf && (
                              <Badge variant="secondary">{t("you")}</Badge>
                            )}
                          </span>
                          {secondaryLabel && (
                            <span className="truncate text-xs text-muted-foreground">
                              {secondaryLabel}
                            </span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(m.joined_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-muted-foreground hover:text-destructive"
                          disabled={isPending && busyId === m.user_id}
                          onClick={() => handleRemove(m.user_id)}
                        >
                          {isPending && busyId === m.user_id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                          <span className="ml-1">
                            {isSelf ? t("leave") : t("remove")}
                          </span>
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
      </section>

      {/* Pending invitations */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-medium">
            {t("invitationsTitle")} ({invitations.length})
          </h2>
          <p className="text-sm text-muted-foreground">
            {t("invitationsDescription")}
          </p>
        </div>
        {invitations.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              {t("noInvitations")}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("recipient")}</TableHead>
                  <TableHead>{t("expires")}</TableHead>
                  <TableHead className="w-0" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {invitations.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        {inv.email ? (
                          <>
                            <Mail className="h-3.5 w-3.5 text-muted-foreground" />
                            {inv.email}
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
                    <TableCell className="text-muted-foreground">
                      {formatDate(inv.expires_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground hover:text-destructive"
                        disabled={isPending && busyId === inv.id}
                        onClick={() => handleRevoke(inv.id)}
                      >
                        {isPending && busyId === inv.id ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Trash2 className="h-4 w-4" />
                        )}
                        <span className="ml-1">{t("revoke")}</span>
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
      </section>

      {/* Invite dialog */}
      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("inviteDialogTitle")}</DialogTitle>
            <DialogDescription>{t("inviteDialogDescription")}</DialogDescription>
          </DialogHeader>

          {createdLink ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {t("inviteLinkHint")}
              </p>
              <div className="flex items-center gap-2">
                <Input readOnly value={createdLink} className="font-mono text-xs" />
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  onClick={handleCopy}
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-green-600" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          ) : (
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
                <p className="text-xs text-muted-foreground">{t("emailHint")}</p>
              </div>
              <div className="space-y-1.5">
                <Label>{t("expiryLabel")}</Label>
                <Select value={expiresInDays} onValueChange={setExpiresInDays}>
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
              {error && <p className="text-sm text-destructive">{error}</p>}
            </div>
          )}

          <DialogFooter>
            {createdLink ? (
              <Button onClick={() => setInviteOpen(false)}>{t("done")}</Button>
            ) : (
              <Button onClick={handleCreate} disabled={isPending}>
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t("createInvite")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

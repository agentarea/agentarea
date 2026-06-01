"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { CheckCircle2, Loader2, MailWarning } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { acceptInvitationAction } from "./actions";

export default function InviteClient({ token }: { token: string | null }) {
  const t = useTranslations("MembersPage");
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);

  const handleAccept = () => {
    if (!token) return;
    setError(null);
    startTransition(async () => {
      const res = await acceptInvitationAction(token);
      if (res.error || !res.data) {
        setError(res.error || t("acceptFailed"));
        return;
      }
      setAccepted(true);
    });
  };

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 pt-10">
      <Card>
        <CardHeader className="space-y-1">
          <CardTitle>{t("acceptTitle")}</CardTitle>
          <CardDescription>{t("acceptDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!token ? (
            <div className="flex items-center gap-2 text-sm text-destructive">
              <MailWarning className="h-4 w-4" />
              {t("acceptNoToken")}
            </div>
          ) : accepted ? (
            <div className="flex flex-col items-center gap-3 py-4 text-center">
              <CheckCircle2 className="h-10 w-10 text-green-600" />
              <p className="text-sm text-muted-foreground">
                {t("acceptSuccess")}
              </p>
              <Button onClick={() => router.push("/workplace")}>
                {t("goToWorkspace")}
              </Button>
            </div>
          ) : (
            <>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button
                className="w-full"
                onClick={handleAccept}
                disabled={isPending}
              >
                {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {t("acceptButton")}
              </Button>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

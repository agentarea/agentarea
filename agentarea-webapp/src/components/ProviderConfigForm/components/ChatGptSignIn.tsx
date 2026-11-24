"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { LogIn } from "lucide-react";
import type { ChatGptDeviceCodeResponse } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  completeChatGptSignInAction,
  startChatGptSignInAction,
} from "@/lib/server-actions";

type Step =
  | { kind: "idle" }
  | { kind: "code"; code: ChatGptDeviceCodeResponse; pending: boolean }
  | { kind: "signedIn" }
  | { kind: "failed"; message: string };

// A configuration of a ChatGPT subscription provider holds a ChatGPT sign-in
// instead of an API key: the device-code login of the Codex CLI.
export default function ChatGptSignIn({ configId }: { configId?: string }) {
  const t = useTranslations("ProviderConfigForm.chatgpt");
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  const start = () =>
    startTransition(async () => {
      if (!configId) return;
      const result = await startChatGptSignInAction(configId);
      setStep(
        result.data
          ? { kind: "code", code: result.data, pending: false }
          : { kind: "failed", message: apiErrorMessage(result, t("failed")) }
      );
    });

  const complete = (code: ChatGptDeviceCodeResponse) =>
    startTransition(async () => {
      if (!configId) return;
      const result = await completeChatGptSignInAction(configId, {
        device_auth_id: code.device_auth_id,
        user_code: code.user_code,
      });
      if (!result.data) {
        setStep({
          kind: "failed",
          message: apiErrorMessage(result, t("failed")),
        });
      } else {
        setStep(
          result.data.signed_in
            ? { kind: "signedIn" }
            : { kind: "code", code, pending: true }
        );
      }
    });

  return (
    <div className="space-y-2">
      <FormLabel htmlFor="chatgpt-sign-in" icon={LogIn}>
        {t("title")}
      </FormLabel>
      <p className="text-xs text-muted-foreground">{t("description")}</p>
      {!configId ? (
        <p className="note">{t("afterCreate")}</p>
      ) : step.kind === "code" ? (
        <div className="space-y-2">
          <p className="text-sm">
            {t("openAndEnter", { url: step.code.verification_uri })}
          </p>
          <a
            href={step.code.verification_uri}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-primary underline"
          >
            {step.code.verification_uri}
          </a>
          <p className="font-mono text-2xl tracking-widest">
            {step.code.user_code}
          </p>
          {step.pending && (
            <p className="text-xs text-muted-foreground">{t("pending")}</p>
          )}
          <Button
            id="chatgpt-sign-in"
            type="button"
            size="xs"
            isLoading={isPending}
            onClick={() => complete(step.code)}
          >
            {t("entered")}
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {step.kind === "signedIn" && (
            <StatusIndicator kind="active">{t("signedIn")}</StatusIndicator>
          )}
          {step.kind === "failed" && (
            <StatusIndicator kind="failed">{step.message}</StatusIndicator>
          )}
          <Button
            id="chatgpt-sign-in"
            type="button"
            size="xs"
            variant={step.kind === "signedIn" ? "outline" : "default"}
            isLoading={isPending}
            onClick={start}
          >
            {step.kind === "idle" ? t("signIn") : t("signInAgain")}
          </Button>
        </div>
      )}
    </div>
  );
}

"use client";

import type {
  ApiKeyCreateResponse,
  ApiKeyResponse,
} from "@/api/client/types.gen";
import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Globe, Key, Loader2 } from "lucide-react";
import AccordionControl from "@/components/AccordionControl";
import FormLabel from "@/components/FormLabel/FormLabel";
import { OneTimeSecretField } from "@/components/SuccessModal";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Note from "@/components/ui/note";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { formatDate } from "@/utils/dateUtils";
import { RevokeKeyAction } from "../../settings/api-keys/APIKeysClient";
import { createAPIKeyAction } from "../../settings/api-keys/actions";

type A2AAccessConfigProps = {
  agentId: string;
  address: string;
  /** This agent's keys; null when the list failed to load. */
  keys: ApiKeyResponse[] | null;
};

export default function A2AAccessConfig({
  agentId,
  address,
  keys,
}: A2AAccessConfigProps) {
  const t = useTranslations("AgentsPage.a2aAccess");
  const locale = useLocale();
  const router = useWorkspaceRouter();
  const [accordionValue, setAccordionValue] = useState("a2a-access");
  const [keyName, setKeyName] = useState("");
  const [isIssuing, setIsIssuing] = useState(false);
  const [issued, setIssued] = useState<ApiKeyCreateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeKeys = (keys ?? []).filter((key) => key.is_active);

  const issue = async () => {
    setIsIssuing(true);
    setError(null);
    try {
      const result = await createAPIKeyAction({
        name: keyName.trim(),
        agent_id: agentId,
      });
      if (result.error || !result.data) {
        setError(`${t("issueFailed")}: ${result.error}`);
        return;
      }
      setIssued(result.data as ApiKeyCreateResponse);
      setKeyName("");
      router.refresh();
    } catch (issueError) {
      console.error("Failed to issue an agent key", issueError);
      setError(t("issueFailed"));
    } finally {
      setIsIssuing(false);
    }
  };

  return (
    <AccordionControl
      id="a2a-access"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={Globe} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={t("note")}
      mainControl={null}
    >
      <div className="space-y-4">
        <div className="space-y-1.5">
          <Label>{t("address")}</Label>
          <CopyableText text={address} />
          <p className="text-xs text-muted-foreground">{t("addressHint")}</p>
        </div>

        <div className="space-y-2">
          <Label>{t("keys")}</Label>
          {keys === null ? (
            <p role="alert" className="text-xs text-destructive">
              {t("keysLoadFailed")}
            </p>
          ) : activeKeys.length === 0 ? (
            <Note className="cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
              <p>{t("noKeys")}</p>
            </Note>
          ) : (
            <ul className="divide-y rounded-md border">
              {activeKeys.map((key) => (
                <li
                  key={key.id}
                  className="group flex items-center gap-3 px-3 py-2 text-xs"
                >
                  <Key className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium">
                      {key.name}
                    </p>
                    <p className="text-muted-foreground">
                      <span className="font-mono">{key.token_prefix}…</span>
                      {" · "}
                      {t("created", { date: formatDate(key.created_at, locale) })}
                      {" · "}
                      {key.last_accessed_at
                        ? t("lastUsed", {
                            when: formatDistanceToNow(
                              new Date(key.last_accessed_at),
                              {
                                addSuffix: true,
                                locale: locale === "ru" ? ru : undefined,
                              }
                            ),
                          })
                        : t("neverUsed")}
                    </p>
                  </div>
                  <RevokeKeyAction apiKey={key} onError={setError} />
                </li>
              ))}
            </ul>
          )}
        </div>

        {issued ? (
          <div className="space-y-2 rounded-md border p-3">
            <OneTimeSecretField
              label={t("issuedLabel", { name: issued.name })}
              icon={Key}
              value={issued.token}
              warning={t("issuedWarning")}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setIssued(null)}
            >
              {t("issuedDone")}
            </Button>
          </div>
        ) : (
          <div className="space-y-1.5">
            <Label htmlFor="a2a-key-name">{t("keyName")}</Label>
            <div className="flex gap-2">
              <Input
                id="a2a-key-name"
                autoComplete="off"
                value={keyName}
                placeholder={t("keyNamePlaceholder")}
                onChange={(event) => setKeyName(event.target.value)}
                onKeyDown={(event) => {
                  // Enter would submit the agent form this section sits in.
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  if (keyName.trim() && !isIssuing) void issue();
                }}
              />
              <Button
                type="button"
                size="sm"
                disabled={!keyName.trim() || isIssuing}
                onClick={issue}
              >
                {isIssuing && <Loader2 className="animate-spin" />}
                {t("issue")}
              </Button>
            </div>
          </div>
        )}
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </AccordionControl>
  );
}

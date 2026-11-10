"use client";

import { useActionState, useState, useTransition } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import {
  Cpu,
  Globe,
  KeyRound,
  Loader2,
  Plus,
  ShieldCheck,
  SquareTerminal,
} from "lucide-react";
import type { ClientResponse, RunnerKeyResponse } from "@/api/client/types.gen";
import FormError from "@/components/FormError";
import {
  CardField,
  EmptyRow,
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import { OneTimeSecretField } from "@/components/SuccessModal";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { getRunnerStatusPresentation } from "@/lib/status";
import { useClientApiUrl } from "@/lib/use-client-api-url";
import {
  issueRunnerKeyAction,
  revokeRunnerKeyAction,
  saveAllowDomainsAction,
  setRunnerModelAction,
  setRunnerSandboxAction,
} from "../actions";

/**
 * A Codex or Claude Code client's runner: whether it is connected, the keys
 * runners hold, the hosts and the model its turns use. `keys` is null for
 * someone who may not edit the client; they see the status and model only.
 */
export function ClientRunner({
  client,
  keys,
}: {
  client: ClientResponse;
  keys: RunnerKeyResponse[] | null;
}) {
  const t = useTranslations("ClientsPage.runner");
  const status = getRunnerStatusPresentation(client.online ?? false);

  return (
    <div className="font-inter h-full w-full overflow-y-auto overscroll-contain bg-muted/20 px-4 pb-11 pt-[18px]">
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <SectionCard>
            <SectionCardHead
              icon={<SquareTerminal />}
              title={t("title")}
              action={
                <StatusIndicator kind={status.kind} size="sm">
                  {t(status.labelKey as "online" | "offline")}
                </StatusIndicator>
              }
            />
            <p className="note px-[15px] py-3">{t("description")}</p>
          </SectionCard>
          {keys !== null && (
            <>
              <RunnerKeys clientId={client.id} kind={client.kind} keys={keys} />
              <RunnerSandbox client={client} />
              <AllowDomains client={client} />
            </>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <RunnerModel client={client} editable={keys !== null} />
        </div>
      </div>
    </div>
  );
}

function RunnerModel({
  client,
  editable,
}: {
  client: ClientResponse;
  editable: boolean;
}) {
  const t = useTranslations("ClientsPage.runner");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const models = client.models ?? [];

  const save = (model: string) => {
    setError(null);
    startTransition(async () => {
      const result = await setRunnerModelAction(client.id, model);
      setError(result.error);
    });
  };

  return (
    <SectionCard>
      <SectionCardHead icon={<Cpu />} title={t("model")} />
      <div className="space-y-2 px-[15px] py-3">
        {models.length === 0 ? (
          <p className="note">{t("modelsPending")}</p>
        ) : (
          <Select
            value={client.default_model ?? undefined}
            onValueChange={save}
            disabled={!editable || pending}
          >
            <SelectTrigger aria-label={t("model")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {models.map((model) => (
                <SelectItem key={String(model.name)} value={String(model.name)}>
                  {String(model.name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <p className="note">{t("modelHint")}</p>
        {error && <FormError>{error}</FormError>}
      </div>
    </SectionCard>
  );
}

function RunnerSandbox({ client }: { client: ClientResponse }) {
  const t = useTranslations("ClientsPage.runner");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const sandbox = client.sandbox ?? true;

  const save = (next: boolean) => {
    setError(null);
    startTransition(async () => {
      const result = await setRunnerSandboxAction(client.id, next);
      setError(result.error);
    });
  };

  return (
    <SectionCard>
      <SectionCardHead
        icon={<ShieldCheck />}
        title={t("sandbox")}
        action={
          <Switch
            checked={sandbox}
            onCheckedChange={save}
            disabled={pending}
            aria-label={t("sandbox")}
          />
        }
      />
      <div className="space-y-2 px-[15px] py-3">
        <p className="note">{sandbox ? t("sandboxOn") : t("sandboxOff")}</p>
        {error && <FormError>{error}</FormError>}
      </div>
    </SectionCard>
  );
}

function AllowDomains({ client }: { client: ClientResponse }) {
  const t = useTranslations("ClientsPage.runner");
  const [state, formAction, pending] = useActionState(
    saveAllowDomainsAction.bind(null, client.id),
    { error: null }
  );

  return (
    <SectionCard>
      <SectionCardHead
        icon={<Globe />}
        title={t("domains")}
        count={(client.allow_domains ?? []).length}
      />
      <form action={formAction} className="space-y-2 px-[15px] py-3">
        <Textarea
          name="allow_domains"
          aria-label={t("domains")}
          rows={3}
          className="font-mono text-xs"
          placeholder="api.example.com"
          defaultValue={(client.allow_domains ?? []).join("\n")}
        />
        <p className="note">{t("domainsHint")}</p>
        {state.error && <FormError>{state.error}</FormError>}
        <Button type="submit" size="sm" variant="outline" disabled={pending}>
          {pending && <Loader2 className="animate-spin" />}
          {t("save")}
        </Button>
      </form>
    </SectionCard>
  );
}

/**
 * The keys this client's runners hold. Issuing one shows, once, the command
 * that registers a runner with it; revoking one cuts that runner off.
 */
function RunnerKeys({
  clientId,
  kind,
  keys,
}: {
  clientId: string;
  kind: string;
  keys: RunnerKeyResponse[];
}) {
  const t = useTranslations("ClientsPage.runner");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  const apiUrl = useClientApiUrl();
  const router = useWorkspaceRouter();
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [issuing, startIssue] = useTransition();
  const [, startRevoke] = useTransition();
  // The API's clock may run ahead of the browser's; a key is never issued "in 5 seconds".
  const ago = (iso: string) =>
    format.relativeTime(Math.min(Date.parse(iso), now.getTime()), now);

  const issue = () => {
    setError(null);
    startIssue(async () => {
      const result = await issueRunnerKeyAction(clientId);
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setKey(result.key);
      router.refresh();
    });
  };

  const revoke = (keyId: string) => {
    setError(null);
    setRevoking(keyId);
    startRevoke(async () => {
      const result = await revokeRunnerKeyAction(clientId, keyId);
      setRevoking(null);
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      router.refresh();
    });
  };

  return (
    <SectionCard>
      <SectionCardHead
        icon={<KeyRound />}
        title={t("keys.title")}
        count={keys.length}
        action={
          <Button
            variant="ghost"
            size="xs"
            className="text-muted-foreground"
            onClick={issue}
            disabled={issuing}
          >
            {issuing ? <Loader2 className="animate-spin" /> : <Plus />}
            {t("connect.issue")}
          </Button>
        }
      />
      {error && (
        <div className="border-b border-border/60 px-[15px] py-2.5">
          <FormError>{error}</FormError>
        </div>
      )}
      {key ? (
        <CardField label={t("connect.title")}>
          <div className="space-y-2">
            <OneTimeSecretField
              label={t("connect.register")}
              icon={SquareTerminal}
              value={`agentarea runner register --api-url ${apiUrl} --key ${key}`}
              warning={t("connect.shownOnce")}
            />
            <p className="note">{t("connect.then")}</p>
            <CopyableText text={`agentarea runner ${kind}`} />
            <Button size="sm" variant="outline" onClick={() => setKey(null)}>
              {t("connect.done")}
            </Button>
          </div>
        </CardField>
      ) : (
        <p className="note border-b border-border/60 px-[15px] py-3">
          {t("connect.description")}
        </p>
      )}
      {keys.length === 0 ? (
        <EmptyRow text={t("keys.empty")} />
      ) : (
        keys.map((runnerKey) => (
          <FactRow
            key={runnerKey.id}
            tile={<SoftTile icon={<KeyRound />} />}
            title={<span className="font-mono">{runnerKey.prefix}…</span>}
            sub={[
              t("keys.issued", { when: ago(runnerKey.created_at) }),
              runnerKey.last_used_at
                ? t("keys.used", { when: ago(runnerKey.last_used_at) })
                : t("keys.neverUsed"),
            ].join(" · ")}
            trailing={
              <Button
                size="xs"
                variant="outline"
                disabled={revoking !== null}
                onClick={() => revoke(runnerKey.id)}
              >
                {revoking === runnerKey.id && (
                  <Loader2 className="animate-spin" />
                )}
                {t("keys.revoke")}
              </Button>
            }
          />
        ))
      )}
    </SectionCard>
  );
}

"use client";

import { useActionState, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Cpu, Globe, KeyRound, Loader2, SquareTerminal } from "lucide-react";
import type { ClientResponse, RunnerKeyResponse } from "@/api/client/types.gen";
import AccordionControl from "@/components/AccordionControl";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { OneTimeSecretField } from "@/components/SuccessModal";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
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
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { getRunnerStatusPresentation } from "@/lib/status";
import { useClientApiUrl } from "@/lib/use-client-api-url";
import {
  issueRunnerKeyAction,
  revokeRunnerKeyAction,
  saveAllowDomainsAction,
  setRunnerModelAction,
} from "./actions";

/**
 * A Codex or Claude Code client's runner: whether it is connected, the model
 * and hosts its turns use, and the keys runners hold. `keys` is null for
 * someone who may not edit the client; they see the status only.
 */
export function ClientRunner({
  client,
  keys,
}: {
  client: ClientResponse;
  keys: RunnerKeyResponse[] | null;
}) {
  const t = useTranslations("ClientsPage.runner");
  const [open, setOpen] = useState("client-runner");
  const status = getRunnerStatusPresentation(client.online ?? false);

  return (
    <AccordionControl
      id="client-runner"
      accordionValue={open}
      setAccordionValue={setOpen}
      title={
        <FormLabel icon={SquareTerminal} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={<p>{t("description")}</p>}
      noteInline
      mainControl={
        <StatusIndicator kind={status.kind} size="sm">
          {t(status.labelKey as "online" | "offline")}
        </StatusIndicator>
      }
    >
      <div className="space-y-5 pt-2">
        <RunnerModel client={client} editable={keys !== null} />
        {keys !== null && (
          <>
            <AllowDomains client={client} />
            <ConnectRunner clientId={client.id} kind={client.kind} />
            <RunnerKeys clientId={client.id} keys={keys} />
          </>
        )}
      </div>
    </AccordionControl>
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
    <div className="space-y-1.5">
      <FormLabel htmlFor="runner-model" icon={Cpu}>
        {t("model")}
      </FormLabel>
      {models.length === 0 ? (
        <p className="note">{t("modelsPending")}</p>
      ) : (
        <Select
          value={client.default_model ?? undefined}
          onValueChange={save}
          disabled={!editable || pending}
        >
          <SelectTrigger id="runner-model" className="max-w-sm">
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
  );
}

function AllowDomains({ client }: { client: ClientResponse }) {
  const t = useTranslations("ClientsPage.runner");
  const [state, formAction, pending] = useActionState(
    saveAllowDomainsAction.bind(null, client.id),
    { error: null }
  );

  return (
    <form action={formAction} className="space-y-1.5">
      <FormLabel htmlFor="runner-domains" icon={Globe}>
        {t("domains")}
      </FormLabel>
      <Textarea
        id="runner-domains"
        name="allow_domains"
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
  );
}

/** Issue a key and show, once, the command that registers a runner with it. */
function ConnectRunner({ clientId, kind }: { clientId: string; kind: string }) {
  const t = useTranslations("ClientsPage.runner.connect");
  const apiUrl = useClientApiUrl();
  const router = useWorkspaceRouter();
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const issue = () => {
    setError(null);
    startTransition(async () => {
      const result = await issueRunnerKeyAction(clientId);
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setKey(result.key);
      router.refresh();
    });
  };

  return (
    <div className="space-y-2">
      <FormLabel icon={KeyRound}>{t("title")}</FormLabel>
      <p className="note">{t("description")}</p>
      {error && <FormError>{error}</FormError>}
      {key ? (
        <div className="space-y-2 rounded-md border p-3">
          <OneTimeSecretField
            label={t("register")}
            icon={SquareTerminal}
            value={`agentarea runner register --api-url ${apiUrl} --key ${key}`}
            warning={t("shownOnce")}
          />
          <p className="note">{t("then")}</p>
          <CopyableText text={`agentarea runner ${kind}`} />
          <Button size="sm" variant="outline" onClick={() => setKey(null)}>
            {t("done")}
          </Button>
        </div>
      ) : (
        <Button size="sm" variant="outline" onClick={issue} disabled={pending}>
          {pending ? <Loader2 className="animate-spin" /> : <KeyRound />}
          {t("issue")}
        </Button>
      )}
    </div>
  );
}

/** The keys this client's runners hold; revoking one cuts that runner off. */
function RunnerKeys({
  clientId,
  keys,
}: {
  clientId: string;
  keys: RunnerKeyResponse[];
}) {
  const t = useTranslations("ClientsPage.runner.keys");
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const revoke = (keyId: string) => {
    setError(null);
    setRevoking(keyId);
    startTransition(async () => {
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
    <div className="space-y-2">
      <FormLabel>{t("title")}</FormLabel>
      {error && <FormError>{error}</FormError>}
      {keys.length === 0 ? (
        <p className="note">{t("empty")}</p>
      ) : (
        <Table
          data={keys}
          columns={[
            {
              header: t("key"),
              accessor: "prefix",
              render: (prefix) => (
                <span className="font-mono text-xs">{String(prefix)}…</span>
              ),
            },
            {
              header: t("created"),
              accessor: "created_at",
              render: (value) => (
                <TableDateDisplay dateString={String(value)} relative oneRow />
              ),
            },
            {
              header: t("lastUsed"),
              accessor: "last_used_at",
              render: (value) =>
                value ? (
                  <TableDateDisplay
                    dateString={String(value)}
                    relative
                    oneRow
                  />
                ) : (
                  "—"
                ),
            },
            {
              header: "",
              accessor: "id",
              cellClassName: "text-right",
              render: (id) => (
                <Button
                  size="xs"
                  variant="outline"
                  disabled={revoking !== null}
                  onClick={() => revoke(String(id))}
                >
                  {revoking === id && <Loader2 className="animate-spin" />}
                  {t("revoke")}
                </Button>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}

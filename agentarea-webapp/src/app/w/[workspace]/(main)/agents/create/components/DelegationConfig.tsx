"use client";

import type {
  AgentCardSummary,
  AgentToolConfig,
  SecretResponse,
} from "@/api/client/types.gen";
import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Globe, Loader2, Trash2 } from "lucide-react";
import Link from "@/components/WorkspaceLink";
import AccordionControl from "@/components/AccordionControl";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { ResourcePicker } from "@/components/ResourcePicker/ResourcePicker";
import { Accordion } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import Note from "@/components/ui/note";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { readAgentCardAction } from "../../shared/actions";
import {
  agentAddress,
  isRemoteDelegate,
  patchDelegate,
  remoteDelegateProblem,
  type RemoteDelegateProblem,
} from "../../shared/delegationTools";

const AgentIcon = ENTITY_ICONS.agent;
const NO_SECRET = "__none__";

type WorkspaceAgent = {
  id: string;
  name: string;
  description?: string | null;
  is_catalog?: boolean;
};

type DelegationConfigProps = {
  /** The agent being edited, left out of its own delegates; absent on create. */
  agentId?: string;
  /** The workspace's agents and secrets; null when the list failed to load. */
  agents: WorkspaceAgent[] | null;
  secrets: SecretResponse[] | null;
  delegates: AgentToolConfig[];
  onDelegatesChange: (delegates: AgentToolConfig[]) => void;
};

function SecretSelect({
  id,
  value,
  secrets,
  onChange,
}: {
  id: string;
  value: string | null | undefined;
  secrets: SecretResponse[];
  onChange: (name: string) => void;
}) {
  const t = useTranslations("AgentsPage.delegationConfig");
  // A secret deleted since it was chosen still shows, so the choice stays visible.
  const names = secrets.map((secret) => secret.name);
  if (value && !names.includes(value)) names.unshift(value);

  return (
    <Select
      value={value || NO_SECRET}
      onValueChange={(next) => onChange(next === NO_SECRET ? "" : next)}
    >
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NO_SECRET}>{t("secretNone")}</SelectItem>
        {names.map((name) => (
          <SelectItem key={name} value={name}>
            {name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function RemoteAgentForm({
  delegates,
  secrets,
  secretsFailed,
  onAdd,
}: {
  delegates: AgentToolConfig[];
  secrets: SecretResponse[];
  secretsFailed: boolean;
  onAdd: (delegate: AgentToolConfig) => void;
}) {
  const t = useTranslations("AgentsPage.delegationConfig");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [instructions, setInstructions] = useState("");
  const [problem, setProblem] = useState<RemoteDelegateProblem | null>(null);
  const [card, setCard] = useState<AgentCardSummary | null>(null);
  const [cardError, setCardError] = useState<string | null>(null);
  const [isReading, setIsReading] = useState(false);

  const readCard = async () => {
    setIsReading(true);
    setCardError(null);
    try {
      const result = await readAgentCardAction(agentAddress(url));
      if (result.error || !result.data) {
        setCard(null);
        setCardError(result.error ?? t("cardFailed"));
        return;
      }
      const read = result.data;
      setCard(read);
      setUrl(read.address);
      if (!name.trim()) setName(read.name);
      if (!instructions.trim()) setInstructions(read.description);
    } catch (error) {
      console.error("Failed to read the agent card", error);
      setCard(null);
      setCardError(t("cardFailed"));
    } finally {
      setIsReading(false);
    }
  };

  const add = () => {
    const address = agentAddress(url);
    const found = remoteDelegateProblem({ name, url: address }, delegates);
    setProblem(found);
    if (found) return;
    onAdd(
      patchDelegate(
        { type: "agent", name: name.trim() },
        {
          a2a_url: address,
          auth_secret_name: secret,
          description_override: instructions,
        }
      )
    );
    setName("");
    setUrl("");
    setSecret("");
    setInstructions("");
    setProblem(null);
    setCard(null);
    setCardError(null);
  };

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{t("externalHint")}</p>
      <div className="space-y-1.5">
        <Label htmlFor="remote-delegate-url">{t("url")}</Label>
        <div className="flex gap-2">
          <Input
            id="remote-delegate-url"
            value={url}
            placeholder={t("urlPlaceholder")}
            onChange={(event) => {
              setUrl(event.target.value);
              setCard(null);
              setCardError(null);
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!url.trim() || isReading}
            onClick={readCard}
          >
            {isReading && <Loader2 className="animate-spin" />}
            {t("readCard")}
          </Button>
        </div>
        {card ? (
          <div className="rounded-md border p-2 text-xs">
            <p className="font-medium">{card.name}</p>
            {card.description && (
              <p className="text-muted-foreground">{card.description}</p>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">{t("urlHint")}</p>
        )}
        {cardError && (
          <p role="alert" className="text-xs text-destructive">
            {cardError}
          </p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="remote-delegate-name">{t("name")}</Label>
        <Input
          id="remote-delegate-name"
          value={name}
          placeholder={t("namePlaceholder")}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="remote-delegate-secret">{t("secret")}</Label>
        <SecretSelect
          id="remote-delegate-secret"
          value={secret}
          secrets={secrets}
          onChange={setSecret}
        />
        <p className="text-xs text-muted-foreground">
          {secretsFailed ? t("secretsLoadFailed") : t("secretHint")}{" "}
          <Link
            href="/secrets"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            {t("manageSecrets")}
          </Link>
        </p>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="remote-delegate-instructions">{t("when")}</Label>
        <Textarea
          id="remote-delegate-instructions"
          value={instructions}
          placeholder={t("whenPlaceholder")}
          onChange={(event) => setInstructions(event.target.value)}
        />
      </div>
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {t(problem)}
        </p>
      )}
      <Button type="button" size="sm" onClick={add}>
        {t("addExternal")}
      </Button>
    </div>
  );
}

export default function DelegationConfig({
  agentId,
  agents,
  secrets,
  delegates,
  onDelegatesChange,
}: DelegationConfigProps) {
  const t = useTranslations("AgentsPage.delegationConfig");
  const router = useWorkspaceRouter();
  const [accordionValue, setAccordionValue] = useState("delegation");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  // Catalog agents are listed but not installed here, so the runtime could
  // not resolve them by name.
  const otherAgents = useMemo(
    () =>
      (agents ?? []).filter(
        (agent) => agent.id !== agentId && !agent.is_catalog
      ),
    [agents, agentId]
  );

  const byName = useMemo(
    () => new Map(otherAgents.map((agent) => [agent.name, agent])),
    [otherAgents]
  );
  const selectedIds = delegates.flatMap((delegate) => {
    const agent = !isRemoteDelegate(delegate) && byName.get(delegate.name);
    return agent ? [agent.id] : [];
  });

  const add = (delegate: AgentToolConfig) => {
    if (delegates.some((d) => d.name === delegate.name)) return;
    onDelegatesChange([...delegates, delegate]);
  };
  const remove = (name: string) =>
    onDelegatesChange(delegates.filter((delegate) => delegate.name !== name));
  const update = (name: string, next: AgentToolConfig) =>
    onDelegatesChange(delegates.map((d) => (d.name === name ? next : d)));

  return (
    <AccordionControl
      id="delegation"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={
        <FormLabel icon={AgentIcon} className="cursor-pointer">
          {t("title")}
        </FormLabel>
      }
      note={t("note")}
      mainControl={
        <ConfigSheet
          title={t("title")}
          description={t("sheetDescription")}
          triggerText={t("add")}
          className="ml-auto"
          open={isSheetOpen}
          onOpenChange={setIsSheetOpen}
        >
          <div className="flex flex-col space-y-6 overflow-y-auto pb-6">
            <section className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <AgentIcon className="h-4 w-4 text-muted-foreground" />
                {t("available")}
              </div>
              <ResourcePicker
                items={otherAgents}
                prefix="delegate"
                selectedIds={selectedIds}
                onAdd={(agent) => add({ type: "agent", name: agent.name })}
                onRemove={(agent) => remove(agent.name)}
                loading={false}
                failed={agents === null}
                onRefresh={() => router.refresh()}
                emptyText={t("noOtherAgents")}
                manageText={t("createAgent")}
                manageHref="/agents/create"
                extractTitle={(agent) => (
                  <span className="flex items-center gap-2">
                    <AgentIcon className="h-4 w-4" />
                    {agent.name}
                  </span>
                )}
              />
            </section>
            <section className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Globe className="h-4 w-4 text-muted-foreground" />
                {t("external")}
              </div>
              <RemoteAgentForm
                delegates={delegates}
                secrets={secrets ?? []}
                secretsFailed={secrets === null}
                onAdd={add}
              />
            </section>
          </div>
        </ConfigSheet>
      }
    >
      {delegates.length > 0 ? (
        <Accordion type="multiple" id="delegates" className="space-y-2">
          {delegates.map((delegate) => {
            const remote = isRemoteDelegate(delegate);
            const local = remote ? undefined : byName.get(delegate.name);
            const Icon = remote ? Globe : AgentIcon;
            const urlInvalid =
              remote &&
              remoteDelegateProblem(
                { name: delegate.name, url: delegate.settings?.a2a_url ?? "" },
                []
              ) === "urlInvalid";
            const field = (key: string) => `delegate-${delegate.name}-${key}`;
            return (
              <CardAccordionItem
                key={delegate.name}
                value={delegate.name}
                title={
                  <div className="flex min-w-0 flex-row items-center gap-2 px-[7px] py-[7px]">
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <h3 className="truncate text-sm font-medium">
                      {delegate.name}
                    </h3>
                    {remote && <Badge variant="outline">A2A</Badge>}
                  </div>
                }
                controls={
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => remove(delegate.name)}
                    className="h-4 w-4 shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                    aria-label={t("remove", { name: delegate.name })}
                  >
                    <Trash2 />
                  </Button>
                }
              >
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <Label htmlFor={field("when")}>{t("when")}</Label>
                    <Textarea
                      id={field("when")}
                      value={delegate.settings?.description_override ?? ""}
                      placeholder={local?.description || t("whenPlaceholder")}
                      onChange={(event) =>
                        update(
                          delegate.name,
                          patchDelegate(delegate, {
                            description_override: event.target.value,
                          })
                        )
                      }
                    />
                    {!remote && (
                      <p className="text-xs text-muted-foreground">
                        {t("whenHintLocal")}
                      </p>
                    )}
                  </div>
                  {remote && (
                    <>
                      <div className="space-y-1.5">
                        <Label htmlFor={field("url")}>{t("url")}</Label>
                        <Input
                          id={field("url")}
                          value={delegate.settings?.a2a_url ?? ""}
                          aria-invalid={urlInvalid}
                          onChange={(event) =>
                            update(
                              delegate.name,
                              patchDelegate(delegate, {
                                a2a_url: event.target.value,
                              })
                            )
                          }
                          onBlur={(event) =>
                            update(
                              delegate.name,
                              patchDelegate(delegate, {
                                a2a_url: agentAddress(event.target.value),
                              })
                            )
                          }
                        />
                        {urlInvalid && (
                          <p role="alert" className="text-xs text-destructive">
                            {t("urlInvalid")}
                          </p>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        <Label htmlFor={field("secret")}>{t("secret")}</Label>
                        <SecretSelect
                          id={field("secret")}
                          value={delegate.settings?.auth_secret_name}
                          secrets={secrets ?? []}
                          onChange={(name) =>
                            update(
                              delegate.name,
                              patchDelegate(delegate, {
                                auth_secret_name: name,
                              })
                            )
                          }
                        />
                      </div>
                    </>
                  )}
                </div>
              </CardAccordionItem>
            );
          })}
        </Accordion>
      ) : (
        <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
          <p>{t("empty")}</p>
        </Note>
      )}
    </AccordionControl>
  );
}

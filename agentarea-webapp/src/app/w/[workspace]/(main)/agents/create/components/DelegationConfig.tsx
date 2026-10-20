"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ChevronDown,
  Globe,
  KeyRound,
  Link2,
  Loader2,
  MessageSquare,
  Tag,
  Trash2,
} from "lucide-react";
import type {
  AgentCardSummary,
  AgentToolConfig,
  SecretResponse,
} from "@/api/client/types.gen";
import AccordionControl from "@/components/AccordionControl";
import { AgentAvatar } from "@/components/AgentAvatar";
import ConfigSheet from "@/components/ConfigSheet";
import FormLabel from "@/components/FormLabel/FormLabel";
import { PickerPanel } from "@/components/ResourcePicker/PickerPanel";
import { ResourcePickerList } from "@/components/ResourcePicker/ResourcePicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Input } from "@/components/ui/input";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import Note from "@/components/ui/note";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import Link from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
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

/**
 * What the external-agent form holds, lifted out of it so the sheet's footer
 * can add it or throw it away.
 */
function useRemoteAgentDraft(
  delegates: AgentToolConfig[],
  onAdd: (delegate: AgentToolConfig) => void
) {
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

  const reset = () => {
    setName("");
    setUrl("");
    setSecret("");
    setInstructions("");
    setProblem(null);
    setCard(null);
    setCardError(null);
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
    reset();
  };

  return {
    name,
    setName,
    url,
    setUrl: (next: string) => {
      setUrl(next);
      setCard(null);
      setCardError(null);
    },
    secret,
    setSecret,
    instructions,
    setInstructions,
    problem,
    card,
    cardError,
    isReading,
    readCard,
    add,
    reset,
  };
}

type RemoteAgentDraft = ReturnType<typeof useRemoteAgentDraft>;

function RemoteAgentForm({
  draft,
  secrets,
  secretsFailed,
}: {
  draft: RemoteAgentDraft;
  secrets: SecretResponse[];
  secretsFailed: boolean;
}) {
  const t = useTranslations("AgentsPage.delegationConfig");
  const { url, card, cardError, isReading, problem } = draft;

  return (
    <div className="space-y-4">
      <p className="note">{t("externalHint")}</p>
      <div className="space-y-2">
        <FormLabel htmlFor="remote-delegate-url" icon={Link2}>
          {t("url")}
        </FormLabel>
        <div className="flex gap-2">
          <Input
            id="remote-delegate-url"
            value={url}
            placeholder={t("urlPlaceholder")}
            onChange={(event) => draft.setUrl(event.target.value)}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!url.trim() || isReading}
            onClick={draft.readCard}
          >
            {isReading && <Loader2 className="animate-spin" />}
            {t("readCard")}
          </Button>
        </div>
        {card ? (
          <div className="flex items-start gap-3 rounded-md border px-3 py-2">
            <Globe className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <p className="truncate text-[13px] font-medium leading-5">
                {card.name}
              </p>
              {card.description && (
                <p className="line-clamp-2 text-xs text-muted-foreground">
                  {card.description}
                </p>
              )}
            </div>
          </div>
        ) : (
          <p className="note">{t("urlHint")}</p>
        )}
        {cardError && (
          <p role="alert" className="form-error">
            {cardError}
          </p>
        )}
      </div>
      <div className="space-y-2">
        <FormLabel htmlFor="remote-delegate-name" icon={Tag}>
          {t("name")}
        </FormLabel>
        <Input
          id="remote-delegate-name"
          value={draft.name}
          placeholder={t("namePlaceholder")}
          onChange={(event) => draft.setName(event.target.value)}
        />
      </div>
      <div className="space-y-2">
        <FormLabel htmlFor="remote-delegate-secret" icon={KeyRound}>
          {t("secret")}
        </FormLabel>
        <SecretSelect
          id="remote-delegate-secret"
          value={draft.secret}
          secrets={secrets}
          onChange={draft.setSecret}
        />
        <p className="note">
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
      <div className="space-y-2">
        <FormLabel htmlFor="remote-delegate-instructions" icon={MessageSquare}>
          {t("when")}
        </FormLabel>
        <Textarea
          id="remote-delegate-instructions"
          className="h-[100px] resize-none"
          value={draft.instructions}
          placeholder={t("whenPlaceholder")}
          onChange={(event) => draft.setInstructions(event.target.value)}
        />
      </div>
      {problem && (
        <p role="alert" className="form-error">
          {t(problem)}
        </p>
      )}
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
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const [accordionValue, setAccordionValue] = useState("delegation");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [tab, setTab] = useState<"workspace" | "external">("workspace");
  const [query, setQuery] = useState("");
  // Delegates whose fields are shown under their row.
  const [openNames, setOpenNames] = useState<string[]>([]);
  const toggleOpen = (name: string) =>
    setOpenNames((names) =>
      names.includes(name)
        ? names.filter((open) => open !== name)
        : [...names, name]
    );
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

  const remoteCount = delegates.filter(isRemoteDelegate).length;

  const add = (delegate: AgentToolConfig) => {
    if (delegates.some((d) => d.name === delegate.name)) return;
    onDelegatesChange([...delegates, delegate]);
  };
  const remove = (name: string) =>
    onDelegatesChange(delegates.filter((delegate) => delegate.name !== name));
  const update = (name: string, next: AgentToolConfig) =>
    onDelegatesChange(delegates.map((d) => (d.name === name ? next : d)));

  const draft = useRemoteAgentDraft(delegates, add);
  // Cancel drops whatever was typed into the form and closes the sheet.
  const cancelExternal = () => {
    draft.reset();
    setIsSheetOpen(false);
  };

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
          panel
        >
          <PickerPanel
            title={t("title")}
            description={t("sheetDescription")}
            // A form has nothing to search.
            onSearch={tab === "workspace" ? setQuery : undefined}
            footer={
              tab === "external" && (
                <div className="flex w-full justify-end gap-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    className="px-2 text-muted-foreground hover:text-foreground"
                    onClick={cancelExternal}
                  >
                    {tCommon("cancel")}
                  </Button>
                  <Button
                    type="button"
                    size="xs"
                    className="px-2"
                    disabled={!draft.url.trim()}
                    onClick={draft.add}
                  >
                    {tCommon("add")}
                  </Button>
                </div>
              )
            }
            tabs={
              <CountSegmentedControl
                layoutId="delegation-tabs"
                value={tab}
                onChange={setTab}
                items={[
                  {
                    value: "workspace",
                    label: t("tabWorkspace"),
                    count: selectedIds.length || undefined,
                  },
                  {
                    value: "external",
                    label: t("tabExternal"),
                    count: remoteCount || undefined,
                  },
                ]}
              />
            }
          >
            {tab === "workspace" ? (
              <ResourcePickerList
                query={query}
                heading={t("available")}
                items={otherAgents}
                selectedIds={selectedIds}
                onAdd={(agent) => add({ type: "agent", name: agent.name })}
                onRemove={(agent) => remove(agent.name)}
                extractTitle={(agent) => agent.name}
                extractSubtitle={(agent) => agent.description}
                renderAvatar={(agent) => (
                  <AgentAvatar agent={agent} size="md" />
                )}
                loading={false}
                failed={agents === null}
                onRefresh={() => router.refresh()}
                iconsType="agent"
                emptyTitle={t("noOtherAgents")}
                createText={t("createAgent")}
                createHref="/agents/create"
              />
            ) : (
              <div className="px-5 py-3">
                <RemoteAgentForm
                  draft={draft}
                  secrets={secrets ?? []}
                  secretsFailed={secrets === null}
                />
              </div>
            )}
          </PickerPanel>
        </ConfigSheet>
      }
    >
      {delegates.length > 0 ? (
        <div className="overflow-hidden rounded-md border">
          {delegates.map((delegate) => {
            const remote = isRemoteDelegate(delegate);
            const local = remote ? undefined : byName.get(delegate.name);
            const open = openNames.includes(delegate.name);
            const urlInvalid =
              remote &&
              remoteDelegateProblem(
                { name: delegate.name, url: delegate.settings?.a2a_url ?? "" },
                []
              ) === "urlInvalid";
            const field = (key: string) => `delegate-${delegate.name}-${key}`;
            const when = delegate.settings?.description_override?.trim();
            return (
              <div
                key={delegate.name}
                // An open delegate reads as one block: its row and its fields
                // share a tint, apart from the rows around it.
                className={cn(
                  "border-b last:border-b-0",
                  open && "bg-muted/40 dark:bg-zinc-700/20"
                )}
              >
                <InteractiveListRow
                  onClick={() => toggleOpen(delegate.name)}
                  selected={open}
                  pressed={open}
                  className="px-3 py-2"
                  selectedClassName=""
                  dividerClassName=""
                  start={
                    remote ? (
                      <EntityAvatar
                        variant="soft"
                        size={24}
                        iconScale={0.45}
                        icon={<Globe strokeWidth={1.85} />}
                        aria-hidden
                      />
                    ) : (
                      <AgentAvatar
                        agent={
                          local ?? { id: delegate.name, name: delegate.name }
                        }
                        size="sm"
                      />
                    )
                  }
                  // The row stays open-looking while its fields are shown.
                  forceHoverActionsVisible={open}
                  indicator={
                    <ChevronDown
                      className={cn(
                        "h-4 w-4 text-muted-foreground transition-transform",
                        open && "rotate-180"
                      )}
                    />
                  }
                  hoverActionsWidth={76}
                  hoverActions={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => remove(delegate.name)}
                      className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive dark:hover:bg-red-500/15 dark:hover:text-red-200"
                      aria-label={t("remove", { name: delegate.name })}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  }
                >
                  {/* Name, then what the agent will be told about it, on
                      one line. */}
                  <div className="flex min-w-0 flex-1 items-baseline gap-2">
                    <span className="shrink-0 text-[13px] font-medium leading-5">
                      {delegate.name}
                    </span>
                    {remote && (
                      <Badge variant="outline" className="shrink-0 self-center">
                        A2A
                      </Badge>
                    )}
                    <span className="truncate text-xs text-muted-foreground">
                      {when ||
                        (remote
                          ? delegate.settings?.a2a_url
                          : local?.description)}
                    </span>
                  </div>
                </InteractiveListRow>
                {open && (
                  // Under the name, past the avatar (12px pad + 24px + 12px gap).
                  <div className="space-y-4 pb-4 pl-12 pr-3 pt-1">
                    <div className="space-y-2">
                      <FormLabel htmlFor={field("when")} icon={MessageSquare}>
                        {t("when")}
                      </FormLabel>
                      <Textarea
                        id={field("when")}
                        className="h-[100px] resize-none"
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
                      {!remote && <p className="note">{t("whenHintLocal")}</p>}
                    </div>
                    {remote && (
                      <>
                        <div className="space-y-2">
                          <FormLabel htmlFor={field("url")} icon={Link2}>
                            {t("url")}
                          </FormLabel>
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
                            <p role="alert" className="form-error">
                              {t("urlInvalid")}
                            </p>
                          )}
                        </div>
                        <div className="space-y-2">
                          <FormLabel htmlFor={field("secret")} icon={KeyRound}>
                            {t("secret")}
                          </FormLabel>
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
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground">
          <p>{t("empty")}</p>
        </Note>
      )}
    </AccordionControl>
  );
}

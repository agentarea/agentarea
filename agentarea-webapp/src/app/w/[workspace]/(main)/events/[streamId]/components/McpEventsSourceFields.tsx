"use client";

import { useTranslations } from "next-intl";
import { Braces, ListChecks, Settings2 } from "lucide-react";
import EntityMark from "@/components/EntityMark";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import WorkspaceLink from "@/components/WorkspaceLink";
import type { AttachableResources } from "@/hooks/use-attachable-resources";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { mcpRefIdentity } from "@/lib/mcp/resolveMcpRef";
import {
  argumentFields,
  mcpEventKinds,
  readArguments,
  selectedMcpEvent,
  type ArgumentField,
  type ArgumentProblem,
  type McpEventsServer,
} from "../mcpEventsSource";
import type { SourceFormValues, SourceKind } from "../sourceRequest";

const UNSET = "__unset__";

/**
 * The MCP Events flavour of the add-source form: a server that offers events,
 * one of its events, the way it arrives, and the event's arguments from its
 * input schema.
 */
export default function McpEventsSourceFields({
  servers,
  resources,
  values,
  onChange,
}: {
  servers: McpEventsServer[];
  resources: AttachableResources;
  values: SourceFormValues;
  onChange: (values: SourceFormValues) => void;
}) {
  const t = useTranslations("EventsPage.sources.dialog.mcp");
  const selected = selectedMcpEvent(servers, values);
  const event = selected?.event;
  const kinds = event ? mcpEventKinds(event) : [];
  const fields = event ? argumentFields(event.inputSchema) : [];
  const { problems } = readArguments(fields, values.arguments ?? {});

  const pickServer = (id: string) =>
    onChange({
      ...values,
      kind: undefined,
      settings: { mcp_instance_id: id },
      arguments: {},
    });

  const pickEvent = (name: string) => {
    const next = selected?.server.events.find((entry) => entry.name === name);
    const offered = next ? mcpEventKinds(next) : [];
    onChange({
      ...values,
      kind: offered.length === 1 ? offered[0] : undefined,
      settings: { ...values.settings, event: name },
      arguments: {},
    });
  };

  const setArgument = (key: string, value: string | boolean) =>
    onChange({
      ...values,
      arguments: { ...values.arguments, [key]: value },
    });

  const McpIcon = ENTITY_ICONS.mcp;

  return (
    <>
      <div className="space-y-2">
        <FormLabel htmlFor="source-mcp-server" icon={McpIcon} required>
          {t("server")}
        </FormLabel>
        {resources.failed.includes("mcps") ? (
          <p role="alert" className="text-xs text-destructive">
            {t("serversLoadFailed")}
          </p>
        ) : !resources.loading && servers.length === 0 ? (
          <p className="note">
            {t("noServers")}{" "}
            <WorkspaceLink href="/connections" className="underline">
              {t("noServersLink")}
            </WorkspaceLink>
          </p>
        ) : (
          <Select
            value={selected?.server.id ?? ""}
            onValueChange={pickServer}
            disabled={resources.loading}
          >
            <SelectTrigger id="source-mcp-server" aria-label={t("server")}>
              <SelectValue
                placeholder={
                  resources.loading
                    ? t("loadingServers")
                    : t("serverPlaceholder")
                }
              />
            </SelectTrigger>
            <SelectContent>
              {servers.map((server) => (
                <SelectItem
                  key={server.id}
                  value={server.id}
                  textValue={server.name}
                  disabled={server.error !== null}
                >
                  <span className="flex items-center gap-2">
                    <EntityMark
                      identity={mcpRefIdentity(
                        server.id,
                        resources.mcpInstances,
                        resources.mcpServers
                      )}
                      className="h-4 w-4 shrink-0 rounded-sm"
                    />
                    <span className="truncate">{server.name}</span>
                    <span className="note truncate">
                      {server.error
                        ? t("listingFailed", { error: server.error })
                        : t("eventCount", { count: server.events.length })}
                    </span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {selected && (
        <div className="space-y-2">
          <FormLabel htmlFor="source-mcp-event" icon={ListChecks} required>
            {t("event")}
          </FormLabel>
          <Select value={event?.name ?? ""} onValueChange={pickEvent}>
            <SelectTrigger id="source-mcp-event" aria-label={t("event")}>
              <SelectValue placeholder={t("eventPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {selected.server.events.map((entry) => (
                <SelectItem
                  key={entry.name}
                  value={entry.name}
                  textValue={entry.name}
                >
                  <span className="font-mono text-xs">{entry.name}</span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {event?.description && <p className="note">{event.description}</p>}
        </div>
      )}

      {event && (
        <div className="space-y-2">
          <FormLabel htmlFor="source-mcp-kind" icon={Settings2} required>
            {t("mode")}
          </FormLabel>
          {kinds.length === 0 ? (
            <p role="alert" className="text-xs text-destructive">
              {t("noMode")}
            </p>
          ) : (
            <>
              <Select
                value={values.kind ?? ""}
                onValueChange={(value) =>
                  onChange({
                    ...values,
                    kind: kinds.find((kind) => kind === value),
                  })
                }
              >
                <SelectTrigger id="source-mcp-kind" aria-label={t("mode")}>
                  <SelectValue placeholder={t("modePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {kinds.map((kind: SourceKind) => (
                    <SelectItem key={kind} value={kind}>
                      {t(`modes.${kind}.label`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <ul className="space-y-1">
                {kinds.map((kind) => (
                  <li key={kind} className="note">
                    <span className="font-medium">
                      {t(`modes.${kind}.label`)}:
                    </span>{" "}
                    {t(`modes.${kind}.hint`)}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {fields.length > 0 && (
        <div className="space-y-3">
          <FormLabel icon={Braces}>{t("arguments")}</FormLabel>
          {fields.map((field) => (
            <ArgumentInput
              key={`${event?.name}:${field.key}`}
              field={field}
              value={values.arguments?.[field.key]}
              problem={problems[field.key]}
              onChange={(value) => setArgument(field.key, value)}
            />
          ))}
        </div>
      )}
    </>
  );
}

function ArgumentInput({
  field,
  value,
  problem,
  onChange,
}: {
  field: ArgumentField;
  value: string | boolean | undefined;
  problem: ArgumentProblem | undefined;
  onChange: (value: string | boolean) => void;
}) {
  const t = useTranslations("EventsPage.sources.dialog.mcp");
  const id = `source-mcp-arg-${field.key}`;
  const text = typeof value === "string" ? value : "";
  const shownProblem = problem && problem !== "required" ? problem : undefined;

  return (
    <div className="space-y-1.5">
      {field.control === "switch" ? (
        <div className="flex items-center justify-between gap-3">
          <FormLabel
            htmlFor={id}
            required={field.required}
            optional={!field.required}
          >
            {field.label}
          </FormLabel>
          <Switch
            id={id}
            checked={value === true}
            onCheckedChange={(checked) => onChange(checked)}
          />
        </div>
      ) : (
        <>
          <FormLabel
            htmlFor={id}
            required={field.required}
            optional={!field.required}
          >
            {field.label}
          </FormLabel>
          {field.control === "choice" ? (
            <Select
              value={text || (field.required ? "" : UNSET)}
              onValueChange={(next) => onChange(next === UNSET ? "" : next)}
            >
              <SelectTrigger id={id} aria-label={field.label}>
                <SelectValue placeholder={t("choicePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {!field.required && (
                  <SelectItem value={UNSET}>{t("notSet")}</SelectItem>
                )}
                {field.options?.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : field.control === "json" ? (
            <Textarea
              id={id}
              value={text}
              rows={3}
              className="font-mono text-xs"
              placeholder={t("jsonPlaceholder")}
              aria-invalid={shownProblem !== undefined}
              onChange={(event) => onChange(event.target.value)}
            />
          ) : (
            <Input
              id={id}
              value={text}
              inputMode={field.control === "text" ? undefined : "decimal"}
              autoComplete="off"
              aria-invalid={shownProblem !== undefined}
              onChange={(event) => onChange(event.target.value)}
            />
          )}
        </>
      )}
      {shownProblem ? (
        <p role="alert" className="text-xs text-destructive">
          {t(`problems.${shownProblem}`)}
        </p>
      ) : (
        field.description && <p className="note">{field.description}</p>
      )}
    </div>
  );
}

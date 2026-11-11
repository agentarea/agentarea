"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Bot, KeyRound, Link2, Radio, Settings2, Tag } from "lucide-react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { AgentSelect, type SelectableAgent } from "@/components/AgentSelect";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import SourceTypeMark from "@/components/SourceTypeMark";
import {
  OneTimeSecretField,
  SuccessModalContent,
} from "@/components/SuccessModal";
import { CopyableText } from "@/components/ui/copyable-text";
import { Dialog } from "@/components/ui/dialog";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { announceFormSubmitting } from "../../agents/shared/useFormSubmittingState";
import SendersField from "../../events/[streamId]/components/SendersField";
import { DEFAULT_SENDERS } from "../../events/[streamId]/senders";
import { createChannelAction } from "./actions";
import {
  missingChannelFields,
  toChannelRequest,
  typedCredentials,
  type ChannelFormValues,
} from "./channelRequest";

export const CREATE_CHANNEL_FORM = "create-channel-form";

/** Why the channel was not made, brought into view: the submit button sits in the header. */
function ChannelError({ message }: { message: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [message]);
  return (
    <div ref={ref} role="alert">
      <FormError>{message}</FormError>
    </div>
  );
}

interface Created {
  triggerId: string;
  type: SourceType;
  ownerOnly: boolean;
  webhookUrl: string | null;
  issued: Record<string, string>;
}

/**
 * A bot in one form: the messenger, its token, who may write and the agent
 * that answers. Submitting makes the stream, its source and the trigger.
 */
export function CreateChannelForm({
  types,
  agents,
}: {
  types: SourceType[];
  agents: SelectableAgent[];
}) {
  const t = useTranslations("ChannelsPage.create");
  const tSenders = useTranslations("EventsPage.sources.senders");
  const router = useWorkspaceRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const inFlight = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<Created | null>(null);
  const { control, register, handleSubmit } = useForm<ChannelFormValues>({
    defaultValues: {
      sourceType: types[0]?.slug ?? "",
      name: "",
      credentials: {},
      settings: {},
      senders: DEFAULT_SENDERS,
      agentId: agents.length === 1 ? agents[0].id : "",
    },
  });
  const typeSlug = useWatch({ control, name: "sourceType" });
  const type = sourceTypeBySlug(types, typeSlug);

  const label = (entry: SourceType, key: string) => {
    if (key === "agent") return t("agent");
    if (key === "senders") return tSenders("label");
    return (
      [...entry.credentials, ...entry.config].find((f) => f.key === key)
        ?.label ?? key
    );
  };

  const submit = handleSubmit(async (values) => {
    if (inFlight.current) return;
    if (!type) {
      setError(t("typePlaceholder"));
      return;
    }
    const missing = missingChannelFields(type, values);
    if (missing.length > 0) {
      setError(
        t("missing", {
          fields: missing.map((key) => label(type, key)).join(", "),
        })
      );
      return;
    }
    setError(null);
    inFlight.current = true;
    announceFormSubmitting(formRef.current, true);
    let result: Awaited<ReturnType<typeof createChannelAction>>;
    try {
      result = await createChannelAction(toChannelRequest(type, values));
    } catch (caught) {
      setError(
        `${t("failed")} ${caught instanceof Error ? caught.message : String(caught)}`
      );
      return;
    } finally {
      inFlight.current = false;
      announceFormSubmitting(formRef.current, false);
    }
    if (result.error !== null) {
      setError(result.error);
      return;
    }
    setCreated({
      triggerId: result.triggerId,
      type,
      ownerOnly:
        Boolean(type.admits_senders) && values.senders.allow === "owner",
      webhookUrl: result.webhookUrl,
      issued: result.issued,
    });
  });

  const open = (triggerId: string) => router.push(`/triggers/${triggerId}`);

  return (
    <>
      <form
        id={CREATE_CHANNEL_FORM}
        ref={formRef}
        onSubmit={submit}
        className="mx-auto flex w-full max-w-[1120px] flex-col gap-6"
      >
        {types.length === 0 && <FormError>{t("noTypes")}</FormError>}

        <div className="space-y-2 md:max-w-sm">
          <FormLabel htmlFor="channel-type" icon={Radio} required>
            {t("type")}
          </FormLabel>
          <Controller
            control={control}
            name="sourceType"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="channel-type" aria-label={t("type")}>
                  <SelectValue placeholder={t("typePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {types.map((entry) => (
                    <SelectItem key={entry.slug} value={entry.slug}>
                      <span className="flex items-center gap-2">
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                          <SourceTypeMark type={entry} inline />
                        </span>
                        {entry.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {type && <p className="note">{type.description}</p>}
        </div>

        <div className="space-y-2 md:max-w-sm">
          <FormLabel htmlFor="channel-name" icon={Tag} optional>
            {t("name")}
          </FormLabel>
          <Input
            id="channel-name"
            placeholder={type?.name}
            maxLength={255}
            autoComplete="off"
            {...register("name")}
          />
        </div>

        {type &&
          typedCredentials(type).map((field) => (
            <div key={`${type.slug}:${field.key}`} className="space-y-2">
              <FormLabel
                htmlFor={`channel-credential-${field.key}`}
                icon={KeyRound}
                required={field.required}
                optional={!field.required}
              >
                {field.label}
              </FormLabel>
              <Input
                id={`channel-credential-${field.key}`}
                type="password"
                autoComplete="off"
                placeholder={field.placeholder}
                className="font-mono"
                {...register(`credentials.${field.key}`)}
              />
            </div>
          ))}

        {type?.config.map((field) => (
          <div key={`${type.slug}:${field.key}`} className="space-y-2">
            <FormLabel
              htmlFor={`channel-setting-${field.key}`}
              icon={Settings2}
              required={field.required && !field.issued}
              optional={!field.required || field.issued}
            >
              {field.label}
            </FormLabel>
            <Input
              id={`channel-setting-${field.key}`}
              autoComplete="off"
              placeholder={field.placeholder}
              {...register(`settings.${field.key}`)}
            />
          </div>
        ))}

        {type?.admits_senders && (
          <Controller
            control={control}
            name="senders"
            render={({ field }) => (
              <SendersField
                id="channel"
                value={field.value}
                onChange={field.onChange}
              />
            )}
          />
        )}

        <Divider />

        <div className="space-y-2 md:max-w-sm">
          <FormLabel htmlFor="channel-agent" icon={Bot} required>
            {t("agent")}
          </FormLabel>
          <Controller
            control={control}
            name="agentId"
            render={({ field }) => (
              <AgentSelect
                id="channel-agent"
                agents={agents}
                value={field.value}
                onChange={field.onChange}
                placeholder={t("agentPlaceholder")}
              />
            )}
          />
          <p className="note">{t("agentHint")}</p>
        </div>

        {error && <ChannelError message={error} />}
      </form>

      <Dialog
        open={created !== null}
        onOpenChange={(next) => {
          if (!next && created) open(created.triggerId);
        }}
      >
        {created && (
          <SuccessModalContent
            title={t("created.title")}
            description={
              created.type.registers_webhook
                ? created.ownerOnly
                  ? t("created.writeAndLink")
                  : t("created.write")
                : t("created.pasteUrl")
            }
            doneLabel={t("created.done")}
            onDone={() => open(created.triggerId)}
          >
            {!created.type.registers_webhook && created.webhookUrl && (
              <div className="min-w-0 space-y-2">
                <FormLabel icon={Link2}>{t("created.urlLabel")}</FormLabel>
                <CopyableText text={created.webhookUrl} />
              </div>
            )}
            {!created.type.registers_webhook &&
              Object.entries(created.issued).map(([key, value]) => (
                <OneTimeSecretField
                  key={key}
                  label={
                    created.type.credentials.find((field) => field.key === key)
                      ?.label ?? key
                  }
                  icon={KeyRound}
                  value={value}
                  warning={t("created.secretWarning")}
                />
              ))}
          </SuccessModalContent>
        )}
      </Dialog>
    </>
  );
}

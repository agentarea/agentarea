"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { KeyRound, Link2, Loader2, Plus, Settings2 } from "lucide-react";
import type {
  StreamSourceTypeResponse,
  WebhookSourceCreated,
} from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SecretSelect } from "@/components/SecretSelect";
import {
  OneTimeSecretField,
  SuccessModalContent,
  SuccessModalDetail,
} from "@/components/SuccessModal";
import {
  BlueprintDialogContent,
  BlueprintFields,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import { Dialog, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { renderTriggerIcon } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import { createStreamSourceAction } from "../actions";
import {
  missingSourceFields,
  toSourceRequest,
  type SourceFormValues,
} from "../sourceRequest";

const EMPTY: SourceFormValues = { secrets: {}, settings: {} };

/**
 * Add a webhook source to a stream: pick its type, point each credential at a
 * workspace secret, then — in the same dialog — the URL to give the sender and
 * any signing secret issued for it, shown once.
 */
export default function AddSourceDialog({
  streamId,
  types,
}: {
  streamId: string;
  types: StreamSourceTypeResponse[];
}) {
  const t = useTranslations("EventsPage.sources");
  const [open, setOpen] = useState(false);
  const [typeId, setTypeId] = useState("");
  const [values, setValues] = useState<SourceFormValues>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<WebhookSourceCreated | null>(null);
  const [pending, startTransition] = useTransition();
  const resources = useAttachableResources({ withSecrets: true });

  const type = types.find((entry) => entry.webhook_type === typeId);
  const missing = type ? missingSourceFields(type, values) : [];

  const reset = () => {
    setTypeId("");
    setValues(EMPTY);
    setError(null);
    setCreated(null);
  };

  const onOpenChange = (next: boolean) => {
    if (pending) return;
    if (!next) reset();
    setOpen(next);
  };

  const submit = () => {
    if (!type) return;
    setError(null);
    startTransition(async () => {
      const result = await createStreamSourceAction(
        streamId,
        toSourceRequest(type, values)
      );
      if (result.error !== null) {
        setError(result.error);
        return;
      }
      setCreated(result.source);
    });
  };

  const setField = (
    group: keyof SourceFormValues,
    key: string,
    value: string
  ) =>
    setValues((previous) => ({
      ...previous,
      [group]: { ...previous[group], [key]: value },
    }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogTrigger asChild>
        <Button className="shrink-0" size="xs">
          <Plus />
          {t("add")}
        </Button>
      </DialogTrigger>
      {created ? (
        <SuccessModalContent
          title={t("created.title")}
          description={t("created.description")}
          doneLabel={t("created.done")}
          onDone={() => onOpenChange(false)}
        >
          {created.webhook_url && (
            <div className="min-w-0 space-y-2">
              <FormLabel icon={Link2}>{t("created.urlLabel")}</FormLabel>
              <CopyableText text={created.webhook_url} />
            </div>
          )}
          {created.signing_secret && (
            <OneTimeSecretField
              label={t("created.secretLabel")}
              icon={KeyRound}
              value={created.signing_secret}
              warning={t("created.secretWarning")}
            />
          )}
          {created.signature_scheme && (
            <SuccessModalDetail label={t("signedWith")}>
              <code className="font-mono text-[12px] text-foreground">
                {created.signature_scheme.header}:{" "}
                {created.signature_scheme.prefix}
                {`hex(HMAC-${created.signature_scheme.algorithm.toUpperCase()})`}
              </code>
            </SuccessModalDetail>
          )}
        </SuccessModalContent>
      ) : (
        <BlueprintDialogContent
          title={t("dialog.title")}
          description={t("dialog.description")}
          note={t("dialog.note")}
          actions={
            <Button
              size="sm"
              onClick={submit}
              disabled={pending || !type || missing.length > 0}
            >
              {pending && <Loader2 className="animate-spin" />}
              {t("dialog.submit")}
            </Button>
          }
        >
          <BlueprintFields>
            <div className="space-y-2">
              <FormLabel htmlFor="source-type" required>
                {t("dialog.type")}
              </FormLabel>
              <Select
                value={typeId}
                onValueChange={(value) => {
                  setTypeId(value);
                  setError(null);
                }}
              >
                <SelectTrigger id="source-type" aria-label={t("dialog.type")}>
                  <SelectValue placeholder={t("dialog.typePlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {types.map((entry) => (
                    <SelectItem
                      key={entry.webhook_type}
                      value={entry.webhook_type}
                    >
                      <span className="flex items-center gap-2">
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                          {renderTriggerIcon(entry, undefined, "h-4 w-4")}
                        </span>
                        {entry.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {type && <p className="note">{type.description}</p>}
            </div>

            {type?.credentials.map((field) => (
              <div key={`${type.webhook_type}:${field.key}`} className="space-y-2">
                <FormLabel
                  htmlFor={`source-secret-${field.key}`}
                  icon={KeyRound}
                  required={field.required !== false}
                  optional={field.required === false}
                >
                  {field.label}
                </FormLabel>
                <SecretSelect
                  id={`source-secret-${field.key}`}
                  secrets={resources.secrets}
                  value={values.secrets[field.key] ?? ""}
                  onChange={(secretId) =>
                    setField("secrets", field.key, secretId)
                  }
                  disabled={
                    resources.loading || resources.failed.includes("secrets")
                  }
                  required={field.required !== false}
                  placeholder={
                    resources.loading
                      ? t("dialog.loadingSecrets")
                      : t("dialog.selectSecret")
                  }
                  searchPlaceholder={t("dialog.selectSecret")}
                  emptyMessage={t("dialog.noSecrets")}
                  createLabel={t("dialog.newSecret")}
                  onCreated={resources.refresh}
                />
                {field.placeholder && (
                  <p className="note">{field.placeholder}</p>
                )}
              </div>
            ))}
            {type && resources.failed.includes("secrets") && (
              <p role="alert" className="text-xs text-destructive">
                {t("dialog.secretsLoadFailed")}
              </p>
            )}

            {type?.config?.map((field) => (
              <div key={`${type.webhook_type}:${field.key}`} className="space-y-2">
                <FormLabel
                  htmlFor={`source-setting-${field.key}`}
                  icon={Settings2}
                  required={field.required !== false}
                  optional={field.required === false}
                >
                  {field.label}
                </FormLabel>
                <Input
                  id={`source-setting-${field.key}`}
                  value={values.settings[field.key] ?? ""}
                  placeholder={field.placeholder}
                  autoComplete="off"
                  onChange={(event) =>
                    setField("settings", field.key, event.target.value)
                  }
                />
              </div>
            ))}

            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
          </BlueprintFields>
        </BlueprintDialogContent>
      )}
    </Dialog>
  );
}

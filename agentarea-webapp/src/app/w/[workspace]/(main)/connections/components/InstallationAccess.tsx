"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import type {
  OAuthInstallation,
  OAuthInstallationBinding,
  OAuthInstallationRepository,
} from "@/api/client";
import { CheckboxList } from "@/components/CheckboxList";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  bindOAuthInstallationAction,
  listOAuthInstallationRepositoriesAction,
  listOAuthInstallationsAction,
} from "@/lib/server-actions";
import {
  bindingChanged,
  bindingRequest,
  initialRepositories,
  installationValue,
  USER_TOKEN,
  type InstallationTarget,
} from "../installation-access";

type Editor = {
  installations: OAuthInstallation[];
  choice: string;
  /** Null while the chosen installation's repositories load. */
  repositories: OAuthInstallationRepository[] | null;
  picked: string[];
};

/**
 * Which installation of the GitHub App a connection signed in through its
 * calls reach: one installation, optionally some of its repositories, or —
 * unbound — every installation the user's own token reaches. Folded to one
 * line until the person asks to change it.
 */
export function InstallationAccess({
  target,
  binding,
  onBound,
}: {
  target: InstallationTarget;
  binding: OAuthInstallationBinding | null;
  onBound: (binding: OAuthInstallationBinding | null) => void;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");
  const tCommon = useTranslations("Common");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const loadRepositories = (choice: string) =>
    startTransition(async () => {
      const { data, error } = await listOAuthInstallationRepositoriesAction(
        target,
        Number(choice)
      );
      if (error || !data) {
        setError(error);
        return;
      }
      const names = data.map((r) => r.name);
      setEditor((e) =>
        e && e.choice === choice
          ? {
              ...e,
              repositories: data,
              picked: initialRepositories(binding, choice, names),
            }
          : e
      );
    });

  const open = () => {
    setError(null);
    startTransition(async () => {
      const { data, error } = await listOAuthInstallationsAction(target);
      if (error || !data) {
        setError(error);
        return;
      }
      const choice = installationValue(binding);
      setEditor({
        installations: data,
        choice,
        repositories: null,
        picked: [],
      });
      if (choice !== USER_TOKEN) loadRepositories(choice);
    });
  };

  const choose = (choice: string) => {
    if (!editor) return;
    setError(null);
    setEditor({ ...editor, choice, repositories: null, picked: [] });
    if (choice !== USER_TOKEN) loadRepositories(choice);
  };

  const save = () => {
    if (!editor) return;
    setError(null);
    startTransition(async () => {
      const { data, error } = await bindOAuthInstallationAction(
        bindingRequest(target, editor.choice, editor.picked)
      );
      if (error) {
        setError(error);
        return;
      }
      setEditor(null);
      onBound(data);
    });
  };

  const summary = !binding
    ? t("accessAllInstallations")
    : binding.repositories?.length
      ? t("accessRepositories", {
          account: binding.account,
          count: binding.repositories.length,
        })
      : t("accessInstallation", { account: binding.account });

  if (!editor) {
    return (
      <div className="space-y-1">
        <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          {summary}
          <Button
            variant="link"
            size="xs"
            className="h-auto px-0"
            onClick={open}
            isLoading={pending}
            disabled={pending}
          >
            {t("accessChange")}
          </Button>
        </p>
        {error && <FormError>{error}</FormError>}
      </div>
    );
  }

  const chosen = editor.installations.find(
    (i) => String(i.id) === editor.choice
  );
  const canSave =
    !pending &&
    (editor.choice === USER_TOKEN || editor.repositories !== null) &&
    bindingChanged(binding, editor.choice, editor.picked);

  return (
    <div className="space-y-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
      <p className="text-xs text-muted-foreground">{t("accessHint")}</p>
      <Select value={editor.choice} onValueChange={choose} disabled={pending}>
        <SelectTrigger className="h-8 text-xs" aria-label={t("accessLabel")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={USER_TOKEN} className="text-xs">
            {t("accessUserToken")}
          </SelectItem>
          {editor.installations.map((i) => (
            <SelectItem key={i.id} value={String(i.id)} className="text-xs">
              {i.account}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {chosen && editor.repositories && (
        <div className="space-y-1.5">
          <p className="text-xs text-muted-foreground">
            {editor.repositories.length
              ? t("accessRepositoriesHint", { account: chosen.account })
              : t("accessNoRepositories")}
          </p>
          {editor.repositories.length > 0 && (
            <CheckboxList
              className="max-h-48 overflow-y-auto"
              items={editor.repositories.map((r) => ({
                value: r.name,
                label: r.name,
              }))}
              selected={editor.picked}
              onChange={(picked) => setEditor({ ...editor, picked })}
              disabled={pending}
            />
          )}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button
          size="xs"
          onClick={save}
          isLoading={pending}
          disabled={!canSave}
        >
          {tCommon("save")}
        </Button>
        <Button
          variant="link"
          size="xs"
          className="h-auto px-0 text-muted-foreground"
          onClick={() => {
            setError(null);
            setEditor(null);
          }}
          disabled={pending}
        >
          {tCommon("cancel")}
        </Button>
      </div>
      {error && <FormError>{error}</FormError>}
    </div>
  );
}

"use client";

import React, { useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, PackagePlus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import FormLabel from "@/components/FormLabel/FormLabel";
import SetupForm from "@/components/SetupForm";
import { cn } from "@/lib/utils";
import type {
  ImportPreview,
  InstallResult,
  EntityKind,
  EntityStatus,
  InstallAction,
  PreviewEntity,
  PreviewIssue,
  InstalledEntity,
} from "@/app/(main)/bundles/types";

type WizardStep = "source" | "review" | "result";

const KIND_LABELS: Record<EntityKind, string> = {
  mcp: "MCP Servers",
  skill: "Skills",
  agent: "Agents",
  automation: "Automations",
};

const ENTITY_ORDER: EntityKind[] = ["agent", "skill", "mcp", "automation"];

function EntityStatusChip({ status }: { status: EntityStatus }) {
  if (status === "will_create") {
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
        will create
      </span>
    );
  }
  if (status === "already_exists") {
    return (
      <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
        already exists
      </span>
    );
  }
  return (
    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
      unsupported
    </span>
  );
}

function ActionChip({ action }: { action: InstallAction }) {
  if (action === "created") {
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
        created
      </span>
    );
  }
  if (action === "reused") {
    return (
      <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
        reused
      </span>
    );
  }
  return (
    <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
      skipped
    </span>
  );
}

function EntityRow({ entity }: { entity: PreviewEntity }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm font-medium">{entity.name}</span>
        {entity.detail && (
          <span className="truncate text-xs text-muted-foreground">{entity.detail}</span>
        )}
      </div>
      <EntityStatusChip status={entity.status} />
    </div>
  );
}

function InstalledEntityRow({ entity }: { entity: InstalledEntity }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1.5">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="truncate text-sm font-medium">{entity.name}</span>
        {entity.detail && (
          <span className="truncate text-xs text-muted-foreground">{entity.detail}</span>
        )}
      </div>
      <ActionChip action={entity.action} />
    </div>
  );
}

function groupEntitiesByKind(entities: PreviewEntity[]): Map<EntityKind, PreviewEntity[]> {
  const map = new Map<EntityKind, PreviewEntity[]>();
  for (const e of entities) {
    const list = map.get(e.kind) ?? [];
    list.push(e);
    map.set(e.kind, list);
  }
  return map;
}

function groupInstalledByKind(entities: InstalledEntity[]): Map<EntityKind, InstalledEntity[]> {
  const map = new Map<EntityKind, InstalledEntity[]>();
  for (const e of entities) {
    const list = map.get(e.kind) ?? [];
    list.push(e);
    map.set(e.kind, list);
  }
  return map;
}

function hasRequiredEmpty(
  schema: ImportPreview["setup"],
  values: Record<string, string | number | boolean>
): boolean {
  return schema.some((field) => {
    if (!field.required) return false;
    const val = values[field.key];
    if (val === undefined || val === null) return true;
    if (typeof val === "string" && val.trim() === "") return true;
    return false;
  });
}

async function callProxy<T>(
  path: string,
  body: unknown
): Promise<{ data: T | null; error: string | null }> {
  try {
    const response = await fetch(`/api/proxy/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const json = await response.json();

    if (!response.ok) {
      const detail = json?.detail;
      if (typeof detail === "string") {
        return { data: null, error: detail };
      }
      if (typeof detail?.message === "string") {
        return { data: null, error: detail.message };
      }
      return { data: null, error: `Request failed (${response.status})` };
    }

    return { data: json as T, error: null };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : "Network error";
    return { data: null, error: message };
  }
}

export default function ImportWizard() {
  const [step, setStep] = useState<WizardStep>("source");

  // Source step
  const [source, setSource] = useState("");
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  // Review step
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [setupValues, setSetupValues] = useState<Record<string, string | number | boolean>>({});
  const [setupErrors, setSetupErrors] = useState<Record<string, string>>({});
  const [installLoading, setInstallLoading] = useState(false);
  const [installError, setInstallError] = useState<string | null>(null);

  // Result step
  const [result, setResult] = useState<InstallResult | null>(null);

  function initSetupValues(preview: ImportPreview) {
    const initial: Record<string, string | number | boolean> = {};
    for (const field of preview.setup) {
      if (field.default !== undefined && field.default !== null) {
        initial[field.key] = field.default;
      }
    }
    setSetupValues(initial);
  }

  async function handleAnalyze() {
    if (!source.trim()) return;
    setAnalyzeLoading(true);
    setAnalyzeError(null);

    const { data, error } = await callProxy<ImportPreview>(
      "v1/bundles/analyze",
      { source: source.trim() }
    );

    setAnalyzeLoading(false);

    if (error || !data) {
      setAnalyzeError(error ?? "Failed to analyze package.");
      return;
    }

    setPreview(data);
    initSetupValues(data);
    setStep("review");
  }

  function handleSetupChange(key: string, value: string | number | boolean) {
    setSetupValues((prev) => ({ ...prev, [key]: value }));
    setSetupErrors((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  async function handleInstall() {
    if (!preview) return;
    setInstallLoading(true);
    setInstallError(null);
    setSetupErrors({});

    const { data, error } = await callProxy<InstallResult>(
      "v1/bundles/install",
      { bundle: preview.bundle, setup_values: setupValues }
    );

    setInstallLoading(false);

    if (error || !data) {
      setInstallError(error ?? "Installation failed.");
      return;
    }

    setResult(data);
    setStep("result");
  }

  function handleReset() {
    setStep("source");
    setSource("");
    setAnalyzeError(null);
    setPreview(null);
    setSetupValues({});
    setSetupErrors({});
    setInstallError(null);
    setResult(null);
  }

  const installDisabled =
    !preview ||
    !preview.installable ||
    installLoading ||
    hasRequiredEmpty(preview?.setup ?? [], setupValues);

  if (step === "source") {
    return (
      <div className="mx-auto max-w-2xl">
        <div className="space-y-2 rounded-lg border border-border/60 bg-white p-6 dark:border-zinc-700/60 dark:bg-zinc-900">
          <div className="grid gap-2">
            <FormLabel htmlFor="package-source" icon={PackagePlus} required>
              Package Source
            </FormLabel>
            <Textarea
              id="package-source"
              placeholder="Paste your agent package YAML or JSON here..."
              value={source}
              onChange={(e) => {
                setSource(e.target.value);
                setAnalyzeError(null);
              }}
              rows={12}
              className={cn(
                "font-mono text-xs",
                analyzeError ? "border-red-300" : ""
              )}
            />
            {analyzeError && (
              <p className="form-error">{analyzeError}</p>
            )}
            <p className="note">
              Paste a valid agent package definition in YAML or JSON format.
            </p>
          </div>
          <div className="flex justify-end pt-2">
            <Button
              onClick={handleAnalyze}
              disabled={!source.trim() || analyzeLoading}
              isLoading={analyzeLoading}
            >
              {!analyzeLoading && "Analyze Package"}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  if (step === "review" && preview) {
    const grouped = groupEntitiesByKind(preview.entities);
    const blockIssues = preview.issues.filter((i) => i.severity === "block");
    const warnIssues = preview.issues.filter((i) => i.severity === "warn");

    return (
      <div className="mx-auto max-w-2xl space-y-4">
        {/* Package header */}
        <div className="rounded-lg border border-border/60 bg-white p-5 dark:border-zinc-700/60 dark:bg-zinc-900">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold">
                {preview.bundle.display_name ?? preview.bundle.name}
              </h2>
              {preview.bundle.description && (
                <p className="mt-1 text-sm text-muted-foreground">
                  {preview.bundle.description}
                </p>
              )}
            </div>
            <span className="shrink-0 rounded bg-zinc-100 px-2 py-0.5 font-mono text-[10px] text-zinc-500 dark:bg-zinc-800">
              v{preview.bundle.schema_version}
            </span>
          </div>
        </div>

        {/* Entities */}
        {preview.entities.length > 0 && (
          <div className="rounded-lg border border-border/60 bg-white dark:border-zinc-700/60 dark:bg-zinc-900">
            <div className="border-b border-border/60 px-5 py-3 dark:border-zinc-700/60">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                What will be installed
              </div>
            </div>
            <div className="divide-y divide-border/40 dark:divide-zinc-700/40">
              {ENTITY_ORDER.map((kind) => {
                const list = grouped.get(kind);
                if (!list || list.length === 0) return null;
                return (
                  <div key={kind} className="px-5 py-3">
                    <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {KIND_LABELS[kind]}
                    </div>
                    <div className="divide-y divide-border/20 dark:divide-zinc-700/20">
                      {list.map((entity) => (
                        <EntityRow key={entity.key} entity={entity} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Issues */}
        {preview.issues.length > 0 && (
          <div className="space-y-2">
            {blockIssues.map((issue, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/30"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
                <p className="text-sm text-red-700 dark:text-red-400">{issue.message}</p>
              </div>
            ))}
            {warnIssues.map((issue, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-900/50 dark:bg-amber-950/30"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                <p className="text-sm text-amber-700 dark:text-amber-400">{issue.message}</p>
              </div>
            ))}
          </div>
        )}

        {/* Setup form */}
        {preview.setup.length > 0 && (
          <div className="rounded-lg border border-border/60 bg-white dark:border-zinc-700/60 dark:bg-zinc-900">
            <div className="border-b border-border/60 px-5 py-3 dark:border-zinc-700/60">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Configuration
              </div>
            </div>
            <div className="px-5 py-4">
              <SetupForm
                schema={preview.setup}
                values={setupValues}
                onChange={handleSetupChange}
                errors={setupErrors}
                disabled={installLoading}
              />
            </div>
          </div>
        )}

        {/* Install error */}
        {installError && (
          <div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900/50 dark:bg-red-950/30">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
            <p className="text-sm text-red-700 dark:text-red-400">{installError}</p>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between gap-3 pt-1">
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={installLoading}
          >
            Back
          </Button>
          <Button
            onClick={handleInstall}
            disabled={installDisabled}
            isLoading={installLoading}
          >
            {!installLoading && "Install Package"}
          </Button>
        </div>
      </div>
    );
  }

  if (step === "result" && result) {
    const grouped = groupInstalledByKind(result.entities);

    return (
      <div className="mx-auto max-w-2xl space-y-4">
        {/* Success header */}
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-5 py-4 dark:border-emerald-900/50 dark:bg-emerald-950/30">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
          <div>
            <p className="text-sm font-medium text-emerald-800 dark:text-emerald-300">
              Package installed successfully
            </p>
            <p className="text-xs text-emerald-700 dark:text-emerald-400">
              {result.bundle_name}
            </p>
          </div>
        </div>

        {/* Installed entities */}
        {result.entities.length > 0 && (
          <div className="rounded-lg border border-border/60 bg-white dark:border-zinc-700/60 dark:bg-zinc-900">
            <div className="border-b border-border/60 px-5 py-3 dark:border-zinc-700/60">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Installed entities
              </div>
            </div>
            <div className="divide-y divide-border/40 dark:divide-zinc-700/40">
              {ENTITY_ORDER.map((kind) => {
                const list = grouped.get(kind);
                if (!list || list.length === 0) return null;
                return (
                  <div key={kind} className="px-5 py-3">
                    <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {KIND_LABELS[kind]}
                    </div>
                    <div className="divide-y divide-border/20 dark:divide-zinc-700/20">
                      {list.map((entity) => (
                        <InstalledEntityRow key={entity.key} entity={entity} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-3 pt-1">
          <Button onClick={handleReset} variant="outline">
            <RotateCcw className="h-4 w-4" />
            Import another
          </Button>
          <Button asChild>
            <Link href="/agents">Go to Agents</Link>
          </Button>
        </div>
      </div>
    );
  }

  return null;
}

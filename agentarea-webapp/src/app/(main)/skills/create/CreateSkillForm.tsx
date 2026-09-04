"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import YAML from "js-yaml";
import {
  Archive,
  Columns,
  Eye,
  FileCode,
  FilePlus,
  FileText,
  Github,
  Info,
  Loader2,
  Lock,
  Pencil,
  Search,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { Streamdown } from "streamdown";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import {
  createSkillAction as createSkill,
  getSkillAction as getSkill,
  getSkillContentAction as getSkillContent,
  uploadSkillAction as uploadSkill,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import type { Skill, SkillContent } from "@/types/skill";

const SKILL_TEMPLATE = `---
name: my-skill
description: One-line description of when Claude should use this skill (this is how Claude decides to load it).
---

# My Skill

Describe what this skill does and when to use it. Keep instructions tight — every line stays in context once loaded.

## When to use

- Trigger condition or example phrase
- Add as many bullets as makes sense

## Instructions

1. Step-by-step guidance.
2. Reference any bundled scripts or files here.
`;

const CONTENT_PLACEHOLDER = `# Skill name

What this skill does and when the agent should reach for it.

## When to use
- The user is trying to…

## Steps
1. …`;

function parseFrontmatter(content: string): {
  hasFrontmatter: boolean;
  name?: string;
  description?: string;
  body: string;
} {
  const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/);
  if (!match) return { hasFrontmatter: false, body: content };
  let parsed: Record<string, unknown> | null = null;
  try {
    parsed = YAML.load(match[1]) as Record<string, unknown> | null;
  } catch {
    parsed = null;
  }
  return {
    hasFrontmatter: true,
    body: match[2] || "",
    name: typeof parsed?.name === "string" ? parsed.name : undefined,
    description:
      typeof parsed?.description === "string" ? parsed.description : undefined,
  };
}

function injectFrontmatter(
  body: string,
  name?: string,
  description?: string
): string {
  const parsed = parseFrontmatter(body);
  if (parsed.hasFrontmatter) return body;
  if (!name && !description) return body;
  const lines = ["---"];
  if (name) lines.push(`name: ${name}`);
  if (description) lines.push(`description: ${description}`);
  lines.push("---", "");
  return `${lines.join("\n")}\n${body}`;
}

const GH_PREFIX = "https://github.com/";

/** Normalize a github.com/ relative path (or a full URL) into an absolute URL. */
function normalizeGithubUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return GH_PREFIX + trimmed.replace(/^\/+/, "");
}

type Source = "content" | "github" | "upload";
type ViewMode = "edit" | "split" | "preview";

/* ---- compact segmented "pill" with the brand hatch wash on the active tab ---- */
function SegPill<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon: React.ReactNode }[];
  size?: "md" | "sm";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "inline-flex gap-0.5 rounded-[9px] border border-border bg-muted p-[3px]",
        className
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              "relative inline-flex items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-md font-medium transition-colors",
              size === "md"
                ? "h-8 px-[13px] text-[12.5px]"
                : "h-[26px] px-[11px] text-[12.5px]",
              active
                ? "bg-background font-semibold text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {/* brand: subtle diagonal hatch wash on the active pill */}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-0 z-0 transition-opacity"
              style={{
                backgroundImage: "var(--hatch-accent)",
                opacity: active ? 1 : 0,
                WebkitMaskImage: "linear-gradient(135deg,transparent,#000)",
                maskImage: "linear-gradient(135deg,transparent,#000)",
              }}
            />
            <span
              className={cn(
                "z-[1] flex",
                active ? "text-primary" : "text-muted-foreground/80"
              )}
            >
              {o.icon}
            </span>
            <span className="z-[1]">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function CreateSkillForm() {
  const { toast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const tCreate = useTranslations("SkillsPage.create");
  const sourceSkillId = searchParams.get("from");

  const [source, setSource] = useState<Source>("content");
  const [isDuplicating, setIsDuplicating] = useState(false);
  const [duplicatedFromId, setDuplicatedFromId] = useState<string | null>(null);

  // Shared identity fields (used by every source).
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  // Content source.
  const [contentMarkdown, setContentMarkdown] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("split");

  const parsedContent = useMemo(
    () => parseFrontmatter(contentMarkdown),
    [contentMarkdown]
  );

  // GitHub source — the owner/repo path after the static github.com/ prefix.
  const [githubRepo, setGithubRepo] = useState("");

  // Upload source.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handleContentSubmit = async () => {
    if (!contentMarkdown.trim()) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("contentRequired"),
        variant: "destructive",
      });
      return;
    }

    const finalContent = injectFrontmatter(
      contentMarkdown,
      name.trim() || undefined,
      description.trim() || undefined
    );

    try {
      const { error } = await createSkill({
        content: finalContent,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
      });

      if (error) {
        toast({
          title: tCreate("error.createFailed"),
          description: (error as { detail?: string })?.detail || tCreate("error.createFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: tCreate("success.skillCreated"), variant: "success" });
      router.push("/skills");
    } catch {
      toast({
        title: tCreate("error.createFailed"),
        description: tCreate("error.createFailed"),
        variant: "destructive",
      });
    }
  };

  const handleGithubSubmit = async () => {
    const githubUrl = normalizeGithubUrl(githubRepo);
    if (!githubUrl) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("githubUrlRequired"),
        variant: "destructive",
      });
      return;
    }

    try {
      const url = new URL(githubUrl);
      if (url.hostname !== "github.com" && url.hostname !== "www.github.com") {
        throw new Error("Invalid GitHub URL");
      }
    } catch {
      toast({
        title: tCreate("validationError"),
        description: tCreate("githubUrlInvalid"),
        variant: "destructive",
      });
      return;
    }

    try {
      const { error } = await createSkill({
        github_url: githubUrl,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
      });

      if (error) {
        toast({
          title: tCreate("error.githubImportFailed"),
          description:
            (error as { detail?: string })?.detail || tCreate("error.githubImportFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: tCreate("success.skillImported"), variant: "success" });
      router.push("/skills");
    } catch {
      toast({
        title: tCreate("error.githubImportFailed"),
        description: tCreate("error.githubImportFailed"),
        variant: "destructive",
      });
    }
  };

  const handleUploadSubmit = async () => {
    if (!uploadFile) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("error.zipRequired"),
        variant: "destructive",
      });
      return;
    }

    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      if (name.trim()) formData.append("name", name.trim());
      if (description.trim()) formData.append("description", description.trim());

      const { error } = await uploadSkill(formData);

      if (error) {
        toast({
          title: tCreate("error.uploadFailed"),
          description: (error as { detail?: string })?.detail || tCreate("error.uploadFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: tCreate("success.skillUploaded"), variant: "success" });
      router.push("/skills");
    } catch {
      toast({
        title: tCreate("error.uploadFailed"),
        description: tCreate("error.uploadFailed"),
        variant: "destructive",
      });
    }
  };

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const acceptFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (file.name.endsWith(".zip")) {
        setUploadFile(file);
      } else {
        toast({
          title: tCreate("error.invalidFile"),
          description: tCreate("error.zipRequired"),
          variant: "destructive",
        });
      }
    },
    [tCreate, toast]
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      acceptFile(e.dataTransfer.files?.[0]);
    },
    [acceptFile]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && !file.name.endsWith(".zip")) e.target.value = "";
    acceptFile(file);
  };

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (source === "content") handleContentSubmit();
    else if (source === "github") handleGithubSubmit();
    else if (source === "upload") handleUploadSubmit();
  };

  useEffect(() => {
    if (!sourceSkillId || duplicatedFromId === sourceSkillId) return;

    let cancelled = false;

    const loadSkillToDuplicate = async () => {
      setIsDuplicating(true);
      try {
        const [skillRes, contentRes] = await Promise.all([
          getSkill(sourceSkillId),
          getSkillContent(sourceSkillId),
        ]);
        if (cancelled) return;

        const sourceSkill = skillRes.data as Skill | undefined;
        const sourceContent = contentRes.data as SkillContent | undefined;

        if (skillRes.error || !sourceSkill) {
          toast({
            title: tCreate("error.duplicateLoadFailed"),
            description: tCreate("error.duplicateLoadFailedDescription"),
            variant: "destructive",
          });
          return;
        }

        setName(sourceSkill.name || "");
        setDescription(sourceSkill.description || "");

        if (sourceSkill.source_type === "github") {
          setSource("github");
          setGithubRepo(
            (sourceSkill.source_url || "").replace(/^https?:\/\/github\.com\//i, "")
          );
        } else {
          setSource("content");
          setContentMarkdown(sourceContent?.content || "");
        }

        setDuplicatedFromId(sourceSkillId);
      } catch {
        if (cancelled) return;
        toast({
          title: tCreate("error.duplicateLoadFailed"),
          description: tCreate("error.duplicateLoadFailedDescription"),
          variant: "destructive",
        });
      } finally {
        if (!cancelled) setIsDuplicating(false);
      }
    };

    loadSkillToDuplicate();
    return () => {
      cancelled = true;
    };
  }, [duplicatedFromId, sourceSkillId, tCreate, toast]);

  const useTemplate = () => {
    if (
      contentMarkdown.trim() &&
      !window.confirm(tCreate("templateOverwriteConfirm"))
    ) {
      return;
    }
    setContentMarkdown(SKILL_TEMPLATE);
    setViewMode("split");
  };

  const sourceHints: Record<Source, string> = {
    content: tCreate("sourceHint.content"),
    github: tCreate("sourceHint.github"),
    upload: tCreate("sourceHint.upload"),
  };

  return (
    <form
      id="create-skill-form"
      onSubmit={handleSubmit}
      className="mx-auto flex w-full max-w-[1120px] flex-col"
    >
      {/* ---------------- source switcher + hint ---------------- */}
      <div className="mb-6 flex flex-wrap items-center gap-x-3.5 gap-y-2">
        <SegPill<Source>
          value={source}
          onChange={setSource}
          options={[
            {
              value: "content",
              label: tCreate("writeContent"),
              icon: <FileCode className="h-3.5 w-3.5" strokeWidth={1.7} />,
            },
            {
              value: "github",
              label: tCreate("importFromGithub"),
              icon: <Github className="h-3.5 w-3.5" strokeWidth={1.7} />,
            },
            {
              value: "upload",
              label: tCreate("uploadFiles"),
              icon: <Upload className="h-3.5 w-3.5" strokeWidth={1.7} />,
            },
          ]}
        />
        <span className="text-[12.5px] text-muted-foreground">
          {sourceHints[source]}
        </span>
      </div>

      {/* ---------------- name + description ---------------- */}
      <div className="mb-6 grid gap-5 md:grid-cols-2">
        <div className="grid gap-2">
          <FormLabel htmlFor="skill-name" icon={Sparkles} required>
            {tCreate("name")}
          </FormLabel>
          <Input
            id="skill-name"
            placeholder={tCreate("namePlaceholder")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="skill-description" icon={FileText} optional>
            {tCreate("descriptionLabel")}
          </FormLabel>
          <Input
            id="skill-description"
            placeholder={tCreate("descriptionPlaceholder")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            autoComplete="off"
          />
        </div>
      </div>

      {/* ---------------- content source ---------------- */}
      {source === "content" && (
        <>
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <FormLabel icon={FileCode} required>
              {tCreate("content")}
            </FormLabel>
            <div className="flex-1" />
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={useTemplate}
            >
              <FilePlus />
              {tCreate("useTemplate")}
            </Button>
            <SegPill<ViewMode>
              value={viewMode}
              onChange={setViewMode}
              size="sm"
              options={[
                {
                  value: "edit",
                  label: tCreate("viewMode.edit"),
                  icon: <Pencil className="h-3.5 w-3.5" strokeWidth={1.7} />,
                },
                {
                  value: "split",
                  label: tCreate("viewMode.split"),
                  icon: <Columns className="h-3.5 w-3.5" strokeWidth={1.7} />,
                },
                {
                  value: "preview",
                  label: tCreate("viewMode.preview"),
                  icon: <Eye className="h-3.5 w-3.5" strokeWidth={1.7} />,
                },
              ]}
            />
          </div>

          {parsedContent.hasFrontmatter && (
            <div className="mb-2.5 flex items-start gap-2 rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{tCreate("frontmatterDetected")}</span>
            </div>
          )}

          {isDuplicating && (
            <div className="mb-2.5 flex items-start gap-2 rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" />
              <span>{tCreate("loadingDuplicate")}</span>
            </div>
          )}

          <div
            className={cn(
              "grid min-h-[460px] overflow-hidden rounded-[10px] border border-border bg-background",
              viewMode === "split" ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1"
            )}
          >
            {(viewMode === "edit" || viewMode === "split") && (
              <div
                className={cn(
                  "flex min-h-0 flex-col",
                  viewMode === "split" && "border-border/70 lg:border-r"
                )}
              >
                <div className="flex h-[33px] items-center gap-1.5 border-b border-border/70 bg-muted/30 px-3.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground/80">
                  <FileCode className="h-3.5 w-3.5" strokeWidth={1.7} />
                  {tCreate("markdownPane")}
                </div>
                <textarea
                  id="content-markdown"
                  placeholder={CONTENT_PLACEHOLDER}
                  className="min-h-0 flex-1 resize-none bg-background p-[17px_19px] font-mono text-[12.5px] leading-[1.75] outline-none focus:outline-none"
                  value={contentMarkdown}
                  onChange={(e) => setContentMarkdown(e.target.value)}
                  spellCheck={false}
                />
              </div>
            )}

            {(viewMode === "preview" || viewMode === "split") && (
              <div className="flex min-h-0 flex-col">
                <div className="flex h-[33px] items-center gap-1.5 border-b border-border/70 bg-muted/30 px-3.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground/80">
                  <Eye className="h-3.5 w-3.5" strokeWidth={1.7} />
                  {tCreate("previewPane")}
                </div>
                <div className="min-h-0 flex-1 overflow-auto p-[19px_23px]">
                  {contentMarkdown.trim() ? (
                    <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-xl prose-h1:mt-1 prose-h1:mb-2 prose-h2:text-base prose-h2:mt-5 prose-h2:mb-2 prose-h3:text-sm prose-h3:mt-4 prose-h3:mb-1.5 prose-p:leading-relaxed prose-pre:bg-muted prose-pre:border prose-pre:border-border/70 prose-pre:rounded-md prose-pre:p-4 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                      <Streamdown>
                        {parsedContent.body || contentMarkdown}
                      </Streamdown>
                    </div>
                  ) : (
                    <div className="flex h-full flex-col items-center justify-center gap-2.5 px-8 text-center text-[13px] text-muted-foreground">
                      <span className="grid h-[42px] w-[42px] place-items-center rounded-[11px] bg-muted text-muted-foreground">
                        <Eye className="h-[18px] w-[18px]" strokeWidth={1.7} />
                      </span>
                      {tCreate("previewEmpty")}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* ---------------- github source ---------------- */}
      {source === "github" && (
        <div className="flex min-h-[460px] flex-col overflow-hidden rounded-[10px] border border-border bg-background">
          <div className="flex flex-wrap items-center gap-2.5 border-b border-border/70 px-[18px] py-4">
            <span className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-muted-foreground">
              <Github className="h-3.5 w-3.5" strokeWidth={1.7} />
              github.com/
            </span>
            <Input
              className="h-10 flex-1"
              placeholder={tCreate("githubRepoPlaceholder")}
              value={githubRepo}
              onChange={(e) => setGithubRepo(e.target.value)}
              autoComplete="off"
            />
            <Button type="submit" variant="outline" size="sm" className="h-10">
              <Search />
              {tCreate("browseRepo")}
            </Button>
          </div>
          <div className="relative flex flex-1 flex-col items-center justify-center gap-2.5 overflow-hidden p-8 text-center">
            {/* brand: diagonal hatch band fading up from the bottom */}
            <span
              aria-hidden
              className="pointer-events-none absolute inset-x-0 bottom-0 h-[90px]"
              style={{
                backgroundImage: "var(--hatch)",
                opacity: 0.5,
                WebkitMaskImage: "linear-gradient(0deg,#000,transparent)",
                maskImage: "linear-gradient(0deg,#000,transparent)",
              }}
            />
            <span className="relative z-[1] grid h-12 w-12 place-items-center rounded-xl bg-muted text-muted-foreground">
              <Github className="h-6 w-6" strokeWidth={1.7} />
            </span>
            <div className="relative z-[1] text-sm font-semibold text-foreground/90">
              {tCreate("githubConnectTitle")}
            </div>
            <div className="relative z-[1] max-w-[360px] text-[12.5px] leading-relaxed text-muted-foreground">
              {tCreate.rich("githubConnectDescription", {
                b: (c) => (
                  <b className="font-semibold text-foreground/80">{c}</b>
                ),
              })}
            </div>
          </div>
        </div>
      )}

      {/* ---------------- upload source ---------------- */}
      {source === "upload" && (
        <div className="flex min-h-[460px] flex-col overflow-hidden rounded-[10px] border border-border bg-background p-3.5">
          <div
            className={cn(
              "group/dz relative flex flex-1 flex-col items-center justify-center gap-2 overflow-hidden rounded-xl border-[1.5px] border-dashed p-8 text-center transition-colors",
              isDragging
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary"
            )}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            {/* brand: diagonal hatch band that grows up from the bottom and
                fills with accent on hover (matches the skill cards) */}
            <span
              aria-hidden
              className={cn(
                "pointer-events-none absolute inset-x-0 bottom-0 transition-[height,opacity] duration-300",
                isDragging
                  ? "h-full opacity-90"
                  : "h-14 opacity-60 group-hover/dz:h-full group-hover/dz:opacity-90"
              )}
              style={{
                backgroundImage: isDragging
                  ? "var(--hatch-accent),var(--hatch)"
                  : "var(--hatch)",
                backgroundPosition: "left bottom",
                WebkitMaskImage: "linear-gradient(0deg,#000,transparent)",
                maskImage: "linear-gradient(0deg,#000,transparent)",
              }}
            />
            {/* accent wash layered in on hover */}
            <span
              aria-hidden
              className={cn(
                "pointer-events-none absolute inset-x-0 bottom-0 transition-[height,opacity] duration-300",
                isDragging
                  ? "h-full opacity-90"
                  : "h-14 opacity-0 group-hover/dz:h-full group-hover/dz:opacity-90"
              )}
              style={{
                backgroundImage: "var(--hatch-accent)",
                backgroundPosition: "left bottom",
                WebkitMaskImage: "linear-gradient(0deg,#000,transparent)",
                maskImage: "linear-gradient(0deg,#000,transparent)",
              }}
            />
            <span className="relative z-[1] grid h-[54px] w-[54px] place-items-center rounded-[15px] border border-primary/20 bg-primary/10 text-primary transition-transform duration-200 group-hover/dz:-translate-y-[3px]">
              <Upload className="h-6 w-6" strokeWidth={1.7} />
            </span>
            <div className="relative z-[1] text-sm font-semibold text-foreground">
              {tCreate.rich("dropTitle", {
                zip: (c) => <b className="font-semibold">{c}</b>,
              })}{" "}
              <label
                htmlFor="file-upload"
                className="cursor-pointer text-primary hover:underline"
              >
                {tCreate("browse")}
              </label>
            </div>
            <div className="relative z-[1] max-w-[380px] text-[12.5px] text-muted-foreground">
              {tCreate("dropSubtitle")}
            </div>
            <input
              id="file-upload"
              type="file"
              accept=".zip"
              className="hidden"
              onChange={handleFileChange}
            />
            <label
              htmlFor="file-upload"
              className="relative z-[1] mt-2 inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border bg-background px-3.5 py-2 text-[12.5px] font-semibold text-foreground/80 shadow-[0_1px_2px_rgba(0,0,0,0.05)] transition-colors hover:border-muted-foreground/40 hover:bg-muted"
            >
              <Archive className="h-3.5 w-3.5 text-muted-foreground" />
              {tCreate("chooseZip")}
            </label>

            {uploadFile ? (
              <div className="relative z-[1] mt-4 inline-flex items-center gap-2 rounded-full bg-secondary px-3 py-1 text-sm font-medium">
                <Archive className="h-4 w-4" />
                {uploadFile.name}
                <button
                  type="button"
                  className="ml-1 grid h-4 w-4 place-items-center rounded-full hover:bg-destructive/20"
                  onClick={(e) => {
                    e.preventDefault();
                    setUploadFile(null);
                  }}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ) : (
              <div className="relative z-[1] mt-4 flex flex-wrap items-center justify-center gap-1.5">
                <Chip icon={<Archive className="h-3.5 w-3.5" />}>
                  {tCreate("chipZipArchive")}
                </Chip>
                <Chip icon={<FileCode className="h-3.5 w-3.5" />}>
                  {tCreate("chipSkillInside")}
                </Chip>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------------- footer meta line ---------------- */}
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Lock className="h-3.5 w-3.5" strokeWidth={1.7} />
        {tCreate("metaScope")}{" "}
        <b className="font-semibold text-foreground/80">
          {tCreate("metaPrivate")}
        </b>
        <span className="text-muted-foreground/60">·</span>
        {tCreate("metaVisibleTo")}{" "}
        <b className="font-semibold text-foreground/80">
          {tCreate("metaWorkspace")}
        </b>
      </div>
    </form>
  );
}

function Chip({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-border bg-background px-2.5 text-[11px] font-medium text-muted-foreground">
      <span className="text-muted-foreground/70">{icon}</span>
      {children}
    </span>
  );
}

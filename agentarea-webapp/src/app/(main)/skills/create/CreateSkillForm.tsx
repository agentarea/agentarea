"use client";

import { useState, useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import {
  FileCode,
  Github,
  Upload,
  Link as LinkIcon,
  FileText,
  Sparkles,
  Eye,
  Pencil,
  Columns,
  FilePlus,
  X,
  Info,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { Streamdown } from "streamdown";
import YAML from "js-yaml";
import { cn } from "@/lib/utils";
import {
  createSkillAction as createSkill,
  uploadSkillAction as uploadSkill,
} from "@/lib/server-actions";
import { useToast } from "@/hooks/use-toast";

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

function injectFrontmatter(body: string, name?: string, description?: string): string {
  const parsed = parseFrontmatter(body);
  if (parsed.hasFrontmatter) return body;
  if (!name && !description) return body;
  const lines = ["---"];
  if (name) lines.push(`name: ${name}`);
  if (description) lines.push(`description: ${description}`);
  lines.push("---", "");
  return `${lines.join("\n")}\n${body}`;
}

type ViewMode = "edit" | "split" | "preview";

export function CreateSkillForm() {
  const { toast } = useToast();
  const router = useRouter();
  const tCreate = useTranslations("SkillsPage.create");
  const [activeTab, setActiveTab] = useState("content");

  // Content tab state
  const [contentName, setContentName] = useState("");
  const [contentDescription, setContentDescription] = useState("");
  const [contentMarkdown, setContentMarkdown] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("split");

  const parsedContent = useMemo(
    () => parseFrontmatter(contentMarkdown),
    [contentMarkdown]
  );

  // GitHub tab state
  const [githubUrl, setGithubUrl] = useState("");
  const [githubName, setGithubName] = useState("");
  const [githubDescription, setGithubDescription] = useState("");

  // Upload tab state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");
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
      contentName.trim() || undefined,
      contentDescription.trim() || undefined
    );

    try {
      const { error } = await createSkill({
        content: finalContent,
        name: contentName.trim() || undefined,
        description: contentDescription.trim() || undefined,
      });

      if (error) {
        toast({
          title: tCreate("error.createFailed"),
          description: (error as any)?.detail || tCreate("error.createFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({
        title: tCreate("success.skillCreated"),
        variant: "success",
      });
      router.push("/skills");
      router.refresh();
    } catch {
      toast({
        title: tCreate("error.createFailed"),
        description: tCreate("error.createFailed"),
        variant: "destructive",
      });
    }
  };

  const handleGithubSubmit = async () => {
    if (!githubUrl.trim()) {
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
        name: githubName || undefined,
        description: githubDescription || undefined,
      });

      if (error) {
        toast({
          title: tCreate("error.githubImportFailed"),
          description:
            (error as any)?.detail || tCreate("error.githubImportFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({
        title: tCreate("success.skillImported"),
        variant: "success",
      });
      router.push("/skills");
      router.refresh();
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
      if (uploadName) formData.append("name", uploadName);
      if (uploadDescription) formData.append("description", uploadDescription);

      const { error } = await uploadSkill(formData);

      if (error) {
        toast({
          title: tCreate("error.uploadFailed"),
          description: (error as any)?.detail || tCreate("error.uploadFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({
        title: tCreate("success.skillUploaded"),
        variant: "success",
      });
      router.push("/skills");
      router.refresh();
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

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);

      if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        const file = e.dataTransfer.files[0];
        if (file.name.endsWith(".zip")) {
          setUploadFile(file);
        } else {
          toast({
            title: tCreate("error.invalidFile"),
            description: tCreate("error.zipRequired"),
            variant: "destructive",
          });
        }
      }
    },
    [tCreate, toast]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0];
      if (file.name.endsWith(".zip")) {
        setUploadFile(file);
      } else {
        toast({
          title: tCreate("error.invalidFile"),
          description: tCreate("error.zipRequired"),
          variant: "destructive",
        });
        e.target.value = "";
      }
    }
  };

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (activeTab === "content") handleContentSubmit();
    else if (activeTab === "github") handleGithubSubmit();
    else if (activeTab === "upload") handleUploadSubmit();
  };

  const useTemplate = () => {
    if (
      contentMarkdown.trim() &&
      !window.confirm(tCreate("templateOverwriteConfirm"))
    ) {
      return;
    }
    setContentMarkdown(SKILL_TEMPLATE);
  };

  // Hide form fields when frontmatter already supplies them
  const showNameField = !parsedContent.hasFrontmatter || !parsedContent.name;
  const showDescriptionField =
    !parsedContent.hasFrontmatter || !parsedContent.description;

  return (
    <form
      id="create-skill-form"
      onSubmit={handleSubmit}
      className="flex h-full min-h-0 flex-col"
    >
      <div className="flex h-full min-h-0 flex-col">
        <Tabs
          value={activeTab}
          onValueChange={setActiveTab}
          className="flex h-full min-h-0 w-full flex-col"
        >
          <div className="mb-4 shrink-0">
            <AnimatedTabs
              activeTab={activeTab}
              onChange={setActiveTab}
              tabs={[
                {
                  value: "content",
                  label: tCreate("contentTab"),
                  icon: <FileCode className="h-4 w-4" />,
                },
                {
                  value: "github",
                  label: tCreate("githubTab"),
                  icon: <Github className="h-4 w-4" />,
                },
                {
                  value: "upload",
                  label: tCreate("uploadTab"),
                  icon: <Upload className="h-4 w-4" />,
                },
              ]}
            />
          </div>

          <TabsContent
            value="content"
            className="flex min-h-0 flex-1 flex-col gap-3 data-[state=inactive]:hidden"
          >
            <div className="grid gap-3 md:grid-cols-2">
              {showNameField && (
                <div className="grid gap-1.5">
                  <FormLabel htmlFor="content-name" icon={Sparkles} required={false}>
                    {tCreate("name")}
                  </FormLabel>
                  <Input
                    id="content-name"
                    placeholder={tCreate("namePlaceholder")}
                    value={contentName}
                    onChange={(e) => setContentName(e.target.value)}
                  />
                </div>
              )}
              {showDescriptionField && (
                <div className="grid gap-1.5">
                  <FormLabel
                    htmlFor="content-description"
                    icon={FileText}
                    required={false}
                  >
                    {tCreate("descriptionOptional")}
                  </FormLabel>
                  <Input
                    id="content-description"
                    placeholder={tCreate("descriptionPlaceholder")}
                    value={contentDescription}
                    onChange={(e) => setContentDescription(e.target.value)}
                  />
                </div>
              )}
            </div>

            {parsedContent.hasFrontmatter && (
              <div className="flex items-start gap-2 rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{tCreate("frontmatterDetected")}</span>
              </div>
            )}

            <div className="flex shrink-0 items-center justify-between gap-2">
              <FormLabel htmlFor="content-markdown" icon={FileCode} required>
                {tCreate("content")}
              </FormLabel>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  onClick={useTemplate}
                  className="text-xs"
                >
                  <FilePlus className="mr-1.5 h-3.5 w-3.5" />
                  {tCreate("useTemplate")}
                </Button>
                <AnimatedTabs
                  layoutId="skill-create-view-mode"
                  tabs={[
                    {
                      value: "edit",
                      label: tCreate("viewMode.edit"),
                      icon: <Pencil className="h-3.5 w-3.5" />,
                    },
                    {
                      value: "split",
                      label: tCreate("viewMode.split"),
                      icon: <Columns className="h-3.5 w-3.5" />,
                    },
                    {
                      value: "preview",
                      label: tCreate("viewMode.preview"),
                      icon: <Eye className="h-3.5 w-3.5" />,
                    },
                  ]}
                  activeTab={viewMode}
                  onChange={(v) => setViewMode(v as ViewMode)}
                  className="w-auto rounded-md border border-border/70 bg-background/60 p-0.5 text-xs font-normal"
                  tabClassName="flex-none px-2 py-1 gap-1"
                  labelClassName="hidden sm:inline"
                  activeIndicatorClassName="bg-background shadow-none ring-1 ring-border/70"
                  hoverIndicatorClassName="bg-muted/60"
                />
              </div>
            </div>

            <div
              className={cn(
                "grid min-h-0 flex-1 overflow-hidden rounded-md border border-input bg-background",
                viewMode === "split" ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1"
              )}
            >
              {(viewMode === "edit" || viewMode === "split") && (
                <div
                  className={cn(
                    "flex min-h-0 flex-col",
                    viewMode === "split" && "lg:border-r border-border/70"
                  )}
                >
                  <textarea
                    id="content-markdown"
                    placeholder={tCreate("contentPlaceholder")}
                    className="h-full min-h-[420px] w-full resize-none bg-background p-4 font-mono text-sm leading-relaxed outline-none focus:outline-none"
                    value={contentMarkdown}
                    onChange={(e) => setContentMarkdown(e.target.value)}
                    spellCheck={false}
                  />
                </div>
              )}

              {(viewMode === "preview" || viewMode === "split") && (
                <div className="flex min-h-0 flex-col overflow-auto bg-muted/20 p-4">
                  {contentMarkdown.trim() ? (
                    <div className="prose prose-sm dark:prose-invert max-w-none prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-xl prose-h1:mt-4 prose-h1:mb-2 prose-h2:text-lg prose-h2:mt-4 prose-h2:mb-2 prose-h3:text-base prose-h3:mt-3 prose-h3:mb-1.5 prose-p:leading-relaxed prose-pre:bg-muted prose-pre:border prose-pre:border-border/70 prose-pre:rounded-md prose-pre:p-4 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                      <Streamdown>
                        {parsedContent.body || contentMarkdown}
                      </Streamdown>
                    </div>
                  ) : (
                    <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                      {tCreate("previewEmpty")}
                    </div>
                  )}
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent
            value="github"
            className="flex min-h-0 flex-col gap-4 data-[state=inactive]:hidden"
          >
            <div className="grid gap-2">
              <FormLabel htmlFor="github-url" icon={LinkIcon} required>
                {tCreate("githubUrl")}
              </FormLabel>
              <Input
                id="github-url"
                placeholder={tCreate("githubUrlPlaceholder")}
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {tCreate("githubUrlHint")}
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-2">
                <FormLabel htmlFor="github-name" icon={Sparkles} required={false}>
                  {tCreate("nameOptional")}
                </FormLabel>
                <Input
                  id="github-name"
                  placeholder={tCreate("nameOverride")}
                  value={githubName}
                  onChange={(e) => setGithubName(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <FormLabel
                  htmlFor="github-description"
                  icon={FileText}
                  required={false}
                >
                  {tCreate("descriptionOptional")}
                </FormLabel>
                <Input
                  id="github-description"
                  placeholder={tCreate("descriptionOverride")}
                  value={githubDescription}
                  onChange={(e) => setGithubDescription(e.target.value)}
                />
              </div>
            </div>
          </TabsContent>

          <TabsContent
            value="upload"
            className="flex min-h-0 flex-col gap-4 data-[state=inactive]:hidden"
          >
            <div
              className={cn(
                "rounded-lg border-2 border-dashed p-8 text-center transition-colors",
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25 hover:border-primary/50"
              )}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
            >
              <div className="flex flex-col items-center justify-center gap-2">
                <Upload className="h-8 w-8 text-muted-foreground" />
                <div className="text-sm text-muted-foreground">
                  <span className="font-semibold">{tCreate("dragDrop")}</span>{" "}
                  <label
                    htmlFor="file-upload"
                    className="cursor-pointer text-primary hover:underline"
                  >
                    {tCreate("browse")}
                  </label>
                  <input
                    id="file-upload"
                    type="file"
                    accept=".zip"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>
                <p className="text-xs text-muted-foreground">
                  {tCreate("uploadHint")}
                </p>
                {uploadFile && (
                  <div className="mt-2 flex items-center gap-2 rounded-full bg-secondary px-3 py-1 text-sm font-medium">
                    <FileCode className="h-4 w-4" />
                    {uploadFile.name}
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="ml-1 h-4 w-4 rounded-full hover:bg-destructive/20"
                      onClick={(e) => {
                        e.preventDefault();
                        setUploadFile(null);
                      }}
                    >
                      <X className="h-3 w-3" />
                    </Button>
                  </div>
                )}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-2">
                <FormLabel htmlFor="upload-name" icon={Sparkles} required={false}>
                  {tCreate("nameOptional")}
                </FormLabel>
                <Input
                  id="upload-name"
                  placeholder={tCreate("nameOverride")}
                  value={uploadName}
                  onChange={(e) => setUploadName(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <FormLabel
                  htmlFor="upload-description"
                  icon={FileText}
                  required={false}
                >
                  {tCreate("descriptionOptional")}
                </FormLabel>
                <Input
                  id="upload-description"
                  placeholder={tCreate("descriptionOverride")}
                  value={uploadDescription}
                  onChange={(e) => setUploadDescription(e.target.value)}
                />
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </form>
  );
}

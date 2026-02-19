"use client";

import { useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { FileCode, Github, Upload, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { createSkill, uploadSkill } from "@/lib/browser-api";
import { useToast } from "@/hooks/use-toast";

interface CreateSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

export default function CreateSkillDialog({
  open,
  onOpenChange,
  onSuccess,
}: CreateSkillDialogProps) {
  const { toast } = useToast();
  const t = useTranslations("SkillsPage");
  const tCreate = useTranslations("SkillsPage.create");
  const [activeTab, setActiveTab] = useState("content");
  const [loading, setLoading] = useState(false);

  // Content tab state
  const [contentName, setContentName] = useState("");
  const [contentDescription, setContentDescription] = useState("");
  const [contentMarkdown, setContentMarkdown] = useState("");

  // GitHub tab state
  const [githubUrl, setGithubUrl] = useState("");
  const [githubName, setGithubName] = useState("");
  const [githubDescription, setGithubDescription] = useState("");

  // Upload tab state
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadName, setUploadName] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const resetForm = () => {
    setContentName("");
    setContentDescription("");
    setContentMarkdown("");
    setGithubUrl("");
    setGithubName("");
    setGithubDescription("");
    setUploadFile(null);
    setUploadName("");
    setUploadDescription("");
    setActiveTab("content");
  };

  const handleClose = () => {
    resetForm();
    onOpenChange(false);
  };

  const handleContentSubmit = async () => {
    if (!contentMarkdown.trim()) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("contentRequired"),
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    try {
      const { error } = await createSkill({
        content: contentMarkdown,
        name: contentName || undefined,
        description: contentDescription || undefined,
      });

      if (error) {
        toast({
          title: t("error.loadSkills"),
          description: (error as any)?.detail || tCreate("error.createFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: t("success.skillUpdated"), description: tCreate("success.skillCreated") });
      resetForm();
      onSuccess();
    } finally {
      setLoading(false);
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

    // GitHub URL validation using parsed hostname
    let hostname: string | null = null;
    try {
      const parsed = new URL(githubUrl);
      hostname = parsed.hostname.toLowerCase();
    } catch {
      hostname = null;
    }

    const allowedGitHubHosts = new Set([
      "github.com",
      "www.github.com",
      "gist.github.com",
    ]);

    if (!hostname || !allowedGitHubHosts.has(hostname)) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("githubUrlInvalid"),
        variant: "destructive",
      });
      return;
    }

    setLoading(true);
    try {
      const { error } = await createSkill({
        github_url: githubUrl,
        name: githubName || undefined,
        description: githubDescription || undefined,
      });

      if (error) {
        const errorDetail = (error as any)?.detail;
        let message = tCreate("error.githubImportFailed");

        if (typeof errorDetail === "string") {
          if (errorDetail.includes("rate limit")) {
            message = tCreate("error.githubRateLimit");
          } else if (errorDetail.includes("not found")) {
            message = tCreate("error.githubNotFound");
          } else {
            message = errorDetail;
          }
        }

        toast({
          title: t("error.loadSkills"),
          description: message,
          variant: "destructive",
        });
        return;
      }

      toast({ title: t("success.skillUpdated"), description: tCreate("success.skillImported") });
      resetForm();
      onSuccess();
    } finally {
      setLoading(false);
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

    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      if (uploadName) formData.append("name", uploadName);
      if (uploadDescription) formData.append("description", uploadDescription);

      const { error } = await uploadSkill(formData);

      if (error) {
        toast({
          title: t("error.loadSkills"),
          description: (error as any)?.detail || tCreate("error.uploadFailed"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: t("success.skillUpdated"), description: tCreate("success.skillUploaded") });
      resetForm();
      onSuccess();
    } finally {
      setLoading(false);
    }
  };

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const file = e.dataTransfer.files[0];
    if (file && file.name.toLowerCase().endsWith(".zip")) {
      setUploadFile(file);
    } else {
      toast({
        title: tCreate("error.invalidFile"),
        description: tCreate("error.zipRequired"),
        variant: "destructive",
      });
    }
  }, [toast, tCreate]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.name.toLowerCase().endsWith(".zip")) {
        setUploadFile(file);
      } else {
        toast({
          title: tCreate("error.invalidFile"),
          description: tCreate("error.zipRequired"),
          variant: "destructive",
        });
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{tCreate("title")}</DialogTitle>
          <DialogDescription>
            {tCreate("description")}
          </DialogDescription>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="content" className="gap-2">
              <FileCode className="h-4 w-4" />
              {tCreate("contentTab")}
            </TabsTrigger>
            <TabsTrigger value="github" className="gap-2">
              <Github className="h-4 w-4" />
              {tCreate("githubTab")}
            </TabsTrigger>
            <TabsTrigger value="upload" className="gap-2">
              <Upload className="h-4 w-4" />
              {tCreate("uploadTab")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="content" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="content-name">{tCreate("name")}</Label>
              <Input
                id="content-name"
                placeholder={tCreate("namePlaceholder")}
                value={contentName}
                onChange={(e) => setContentName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="content-description">{tCreate("description")}</Label>
              <Input
                id="content-description"
                placeholder={tCreate("descriptionPlaceholder")}
                value={contentDescription}
                onChange={(e) => setContentDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="content-markdown">
                {tCreate("content")} <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="content-markdown"
                placeholder={tCreate("contentPlaceholder")}
                className="min-h-[200px] font-mono text-sm"
                value={contentMarkdown}
                onChange={(e) => setContentMarkdown(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleContentSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {tCreate("createSkill")}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="github" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="github-url">
                {tCreate("githubUrl")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="github-url"
                placeholder={tCreate("githubUrlPlaceholder")}
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {tCreate("githubDescription")}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="github-name">{tCreate("nameOptional")}</Label>
              <Input
                id="github-name"
                placeholder={tCreate("nameOverride")}
                value={githubName}
                onChange={(e) => setGithubName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="github-description">{tCreate("descriptionOptional")}</Label>
              <Input
                id="github-description"
                placeholder={tCreate("descriptionOverride")}
                value={githubDescription}
                onChange={(e) => setGithubDescription(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleGithubSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {tCreate("importFromGithub")}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="upload" className="space-y-4 pt-4">
            <div
              className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
                isDragging
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/25"
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              {uploadFile ? (
                <div className="space-y-2">
                  <p className="font-medium">{uploadFile.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {(uploadFile.size / 1024).toFixed(1)} KB
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setUploadFile(null)}
                  >
                    {tCreate("remove")}
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Upload className="mx-auto h-8 w-8 text-muted-foreground" />
                  <p className="text-muted-foreground">
                    {tCreate("dragDrop")}{" "}
                    <label className="cursor-pointer text-primary hover:underline">
                      {tCreate("browse")}
                      <input
                        type="file"
                        accept=".zip"
                        className="hidden"
                        onChange={handleFileSelect}
                      />
                    </label>
                  </p>
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="upload-name">{tCreate("nameOptional")}</Label>
              <Input
                id="upload-name"
                placeholder={tCreate("nameOverride")}
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="upload-description">{tCreate("descriptionOptional")}</Label>
              <Input
                id="upload-description"
                placeholder={tCreate("descriptionOverride")}
                value={uploadDescription}
                onChange={(e) => setUploadDescription(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleUploadSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                {tCreate("uploadSkill")}
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

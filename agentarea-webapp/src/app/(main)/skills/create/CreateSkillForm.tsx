"use client";

import { useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { FileCode, Github, Upload, Link as LinkIcon, FileText, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { MarkdownTextarea } from "@/components/ui/markdown-textarea";
import { AnimatedTabs } from "@/components/ui/animated-tabs";
import { createSkillAction as createSkill, uploadSkillAction as uploadSkill } from "@/lib/server-actions";
import { useToast } from "@/hooks/use-toast";

export function CreateSkillForm() {
  const { toast } = useToast();
  const router = useRouter();
  const tCreate = useTranslations("SkillsPage.create");
  const [activeTab, setActiveTab] = useState("content");

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

  const handleContentSubmit = async () => {
    if (!contentMarkdown.trim()) {
      toast({
        title: tCreate("validationError"),
        description: tCreate("contentRequired"),
        variant: "destructive",
      });
      return;
    }

    try {
      const { error } = await createSkill({
        content: contentMarkdown,
        name: contentName || undefined,
        description: contentDescription || undefined,
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
    } catch (err) {
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
          description: (error as any)?.detail || tCreate("error.githubImportFailed"),
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
    } catch (err) {
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
    } catch (err) {
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

  const onDrop = useCallback((e: React.DragEvent) => {
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
  }, [tCreate, toast]);

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
        e.target.value = ""; // Reset input
      }
    }
  };

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (activeTab === "content") handleContentSubmit();
    else if (activeTab === "github") handleGithubSubmit();
    else if (activeTab === "upload") handleUploadSubmit();
  };

  return (
    <form id="create-skill-form" onSubmit={handleSubmit} className="overflow-auto h-full">
      <div className="form-content lg:max-w-xl lg:mx-auto">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
          <div className="mb-6">
            <AnimatedTabs
              activeTab={activeTab}
              onChange={setActiveTab}
              tabs={[
                { value: "content", label: tCreate("contentTab"), icon: <FileCode className="h-4 w-4" /> },
                { value: "github", label: tCreate("githubTab"), icon: <Github className="h-4 w-4" /> },
                { value: "upload", label: tCreate("uploadTab"), icon: <Upload className="h-4 w-4" /> },
              ]}
            />
          </div>

          <TabsContent value="content" className="space-y-4">
            <div className="grid gap-4">
              <div className="grid gap-2">
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
              <div className="grid gap-2">
                <FormLabel htmlFor="content-description" icon={FileText} required={false}>
                  {tCreate("descriptionOptional")}
                </FormLabel>
                <Input
                  id="content-description"
                  placeholder={tCreate("descriptionPlaceholder")}
                  value={contentDescription}
                  onChange={(e) => setContentDescription(e.target.value)}
                />
              </div>
              <div className="grid gap-2">
                <FormLabel htmlFor="content-markdown" icon={FileCode} required>
                  {tCreate("content")}
                </FormLabel>
                <div className="min-h-[300px]">
                  <MarkdownTextarea
                    id="content-markdown"
                    placeholder={tCreate("contentPlaceholder")}
                    className="min-h-[300px] h-full"
                    value={contentMarkdown}
                    onChange={setContentMarkdown}
                  />
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="github" className="space-y-4">
            <div className="grid gap-4">
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
                  {tCreate("githubDescription")}
                </p>
              </div>
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
                <FormLabel htmlFor="github-description" icon={FileText} required={false}>
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

          <TabsContent value="upload" className="space-y-4">
            <div className="grid gap-4">
              <div 
                className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
                  isDragging 
                    ? "border-primary bg-primary/5" 
                    : "border-muted-foreground/25 hover:border-primary/50"
                }`}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
              >
                <div className="flex flex-col items-center justify-center gap-2">
                  <Upload className="h-8 w-8 text-muted-foreground" />
                  <div className="text-sm text-muted-foreground">
                    <span className="font-semibold">{tCreate("dragDrop")}</span>{" "}
                    <label htmlFor="file-upload" className="text-primary hover:underline cursor-pointer">
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
                  {uploadFile && (
                    <div className="mt-2 flex items-center gap-2 text-sm font-medium bg-secondary px-3 py-1 rounded-full">
                      <FileCode className="h-4 w-4" />
                      {uploadFile.name}
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        className="h-4 w-4 ml-1 rounded-full hover:bg-destructive/20"
                        onClick={(e) => {
                          e.preventDefault();
                          setUploadFile(null);
                        }}
                      >
                        ×
                      </Button>
                    </div>
                  )}
                </div>
              </div>

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
                <FormLabel htmlFor="upload-description" icon={FileText} required={false}>
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

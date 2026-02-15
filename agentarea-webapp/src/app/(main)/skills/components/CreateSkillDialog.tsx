"use client";

import { useState, useCallback } from "react";
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
        title: "Validation Error",
        description: "Please enter skill content",
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
          title: "Error",
          description: (error as any)?.detail || "Failed to create skill",
          variant: "destructive",
        });
        return;
      }

      toast({ title: "Success", description: "Skill created successfully" });
      resetForm();
      onSuccess();
    } finally {
      setLoading(false);
    }
  };

  const handleGithubSubmit = async () => {
    if (!githubUrl.trim()) {
      toast({
        title: "Validation Error",
        description: "Please enter a GitHub URL",
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
        title: "Validation Error",
        description: "Please enter a valid GitHub URL",
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
        let message = "Failed to import skill from GitHub";

        if (typeof errorDetail === "string") {
          if (errorDetail.includes("rate limit")) {
            message = "GitHub rate limit exceeded. Please try again later.";
          } else if (errorDetail.includes("not found")) {
            message = "Repository not found or is private.";
          } else {
            message = errorDetail;
          }
        }

        toast({
          title: "Error",
          description: message,
          variant: "destructive",
        });
        return;
      }

      toast({ title: "Success", description: "Skill imported successfully" });
      resetForm();
      onSuccess();
    } finally {
      setLoading(false);
    }
  };

  const handleUploadSubmit = async () => {
    if (!uploadFile) {
      toast({
        title: "Validation Error",
        description: "Please select a ZIP file to upload",
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
          title: "Error",
          description: (error as any)?.detail || "Failed to upload skill",
          variant: "destructive",
        });
        return;
      }

      toast({ title: "Success", description: "Skill uploaded successfully" });
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
        title: "Invalid File",
        description: "Please upload a ZIP file",
        variant: "destructive",
      });
    }
  }, [toast]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (file.name.toLowerCase().endsWith(".zip")) {
        setUploadFile(file);
      } else {
        toast({
          title: "Invalid File",
          description: "Please upload a ZIP file",
          variant: "destructive",
        });
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Add Skill</DialogTitle>
          <DialogDescription>
            Create a new skill from content, import from GitHub, or upload a package.
          </DialogDescription>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="content" className="gap-2">
              <FileCode className="h-4 w-4" />
              Content
            </TabsTrigger>
            <TabsTrigger value="github" className="gap-2">
              <Github className="h-4 w-4" />
              GitHub
            </TabsTrigger>
            <TabsTrigger value="upload" className="gap-2">
              <Upload className="h-4 w-4" />
              Upload
            </TabsTrigger>
          </TabsList>

          <TabsContent value="content" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="content-name">Name</Label>
              <Input
                id="content-name"
                placeholder="My Skill"
                value={contentName}
                onChange={(e) => setContentName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="content-description">Description</Label>
              <Input
                id="content-description"
                placeholder="What this skill does..."
                value={contentDescription}
                onChange={(e) => setContentDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="content-markdown">
                Content <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="content-markdown"
                placeholder="Enter skill content in Markdown..."
                className="min-h-[200px] font-mono text-sm"
                value={contentMarkdown}
                onChange={(e) => setContentMarkdown(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleContentSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create Skill
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="github" className="space-y-4 pt-4">
            <div className="space-y-2">
              <Label htmlFor="github-url">
                GitHub URL <span className="text-red-500">*</span>
              </Label>
              <Input
                id="github-url"
                placeholder="https://github.com/owner/repo"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Public repository containing skill definition
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="github-name">Name (optional)</Label>
              <Input
                id="github-name"
                placeholder="Override imported name"
                value={githubName}
                onChange={(e) => setGithubName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="github-description">Description (optional)</Label>
              <Input
                id="github-description"
                placeholder="Override imported description"
                value={githubDescription}
                onChange={(e) => setGithubDescription(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleGithubSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Import from GitHub
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
                    Remove
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  <Upload className="mx-auto h-8 w-8 text-muted-foreground" />
                  <p className="text-muted-foreground">
                    Drag and drop a ZIP file, or{" "}
                    <label className="cursor-pointer text-primary hover:underline">
                      browse
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
              <Label htmlFor="upload-name">Name (optional)</Label>
              <Input
                id="upload-name"
                placeholder="Override package name"
                value={uploadName}
                onChange={(e) => setUploadName(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="upload-description">Description (optional)</Label>
              <Input
                id="upload-description"
                placeholder="Override package description"
                value={uploadDescription}
                onChange={(e) => setUploadDescription(e.target.value)}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={handleUploadSubmit} disabled={loading}>
                {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Upload Skill
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

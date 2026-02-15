"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import {
  ArrowLeft,
  FileCode,
  Github,
  Upload,
  Trash2,
  Save,
  Loader2,
  ExternalLink,
  File,
} from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getSkill,
  getSkillContent,
  getSkillFiles,
  updateSkill,
  deleteSkill,
  type Skill,
  type SkillContent,
  type SkillFile,
} from "@/lib/browser-api";
import { useToast } from "@/hooks/use-toast";

function getSourceIcon(sourceType: string) {
  switch (sourceType) {
    case "github":
      return <Github className="h-4 w-4" />;
    case "upload":
      return <Upload className="h-4 w-4" />;
    default:
      return <FileCode className="h-4 w-4" />;
  }
}

function getSourceLabel(sourceType: string) {
  switch (sourceType) {
    case "github":
      return "GitHub";
    case "upload":
      return "Uploaded";
    default:
      return "Content";
  }
}

export default function SkillDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { toast } = useToast();
  const skillId = params.id as string;

  const [skill, setSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<SkillContent | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Edit state
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editContent, setEditContent] = useState("");
  const [hasChanges, setHasChanges] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const [skillRes, contentRes, filesRes] = await Promise.all([
          getSkill(skillId),
          getSkillContent(skillId),
          getSkillFiles(skillId),
        ]);

        if (skillRes.error || !skillRes.data) {
          toast({
            title: "Error",
            description: "Skill not found",
            variant: "destructive",
          });
          router.push("/skills");
          return;
        }

        const skillData = skillRes.data as Skill;
        const contentData = contentRes.data as SkillContent;
        const filesData = (filesRes.data as { files: SkillFile[] })?.files || [];

        setSkill(skillData);
        setContent(contentData);
        setFiles(filesData);

        // Initialize edit state
        setEditName(skillData.name);
        setEditDescription(skillData.description || "");
        setEditContent(contentData?.content || "");
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [skillId, router, toast]);

  useEffect(() => {
    if (!skill || !content) return;

    const nameChanged = editName !== skill.name;
    const descChanged = editDescription !== (skill.description || "");
    const contentChanged =
      skill.source_type === "content" && editContent !== (content?.content || "");

    setHasChanges(nameChanged || descChanged || contentChanged);
  }, [editName, editDescription, editContent, skill, content]);

  const handleSave = async () => {
    if (!skill) return;

    setSaving(true);
    try {
      const updateData: any = {
        name: editName,
        description: editDescription || null,
      };

      if (skill.source_type === "content") {
        updateData.content = editContent;
      }

      const { error } = await updateSkill(skillId, updateData);

      if (error) {
        toast({
          title: "Error",
          description: "Failed to update skill",
          variant: "destructive",
        });
        return;
      }

      // Refresh data
      const [skillRes, contentRes] = await Promise.all([
        getSkill(skillId),
        getSkillContent(skillId),
      ]);

      if (skillRes.data) {
        setSkill(skillRes.data as Skill);
      }
      if (contentRes.data) {
        setContent(contentRes.data as SkillContent);
      }

      toast({ title: "Success", description: "Skill updated successfully" });
      setHasChanges(false);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const { error } = await deleteSkill(skillId);

      if (error) {
        toast({
          title: "Error",
          description: "Failed to delete skill",
          variant: "destructive",
        });
        return;
      }

      toast({ title: "Success", description: "Skill deleted successfully" });
      router.push("/skills");
    } finally {
      setDeleting(false);
    }
  };

  if (loading) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: "Skills", href: "/skills" },
            { label: "Loading..." },
          ],
        }}
      >
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      </ContentBlock>
    );
  }

  if (!skill) {
    return null;
  }

  const isContentEditable = skill.source_type === "content";

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Skills", href: "/skills" },
          { label: skill.name },
        ],
        controls: (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="xs"
              onClick={handleSave}
              disabled={!hasChanges || saving}
            >
              {saving ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Save className="mr-2 h-4 w-4" />
              )}
              Save Changes
            </Button>

            <Button
              variant="destructive"
              size="xs"
              disabled={deleting}
              onClick={() => {
                if (window.confirm(`Are you sure you want to delete "${skill.name}"? This action cannot be undone.`)) {
                  handleDelete();
                }
              }}
            >
              {deleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-2 h-4 w-4" />
              )}
              Delete
            </Button>
          </div>
        ),
      }}
    >
      <div className="space-y-6 p-6">
        {/* Metadata Section */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Skill Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Source</Label>
                <div className="flex items-center gap-2 pt-2">
                  <Badge variant="outline" className="gap-1">
                    {getSourceIcon(skill.source_type)}
                    {getSourceLabel(skill.source_type)}
                  </Badge>
                  {skill.source_url && (
                    <a
                      href={skill.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                    >
                      View Source
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="description">Description</Label>
              <Input
                id="description"
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                placeholder="No description"
              />
            </div>
            <div className="flex gap-4 text-sm text-muted-foreground">
              <span>
                Created{" "}
                {formatDistanceToNow(new Date(skill.created_at), {
                  addSuffix: true,
                })}
              </span>
              <span>
                Updated{" "}
                {formatDistanceToNow(new Date(skill.updated_at), {
                  addSuffix: true,
                })}
              </span>
            </div>
          </CardContent>
        </Card>

        {/* Content Section */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Content</CardTitle>
          </CardHeader>
          <CardContent>
            {isContentEditable ? (
              <Textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="min-h-[300px] font-mono text-sm"
                placeholder="Enter skill content..."
              />
            ) : (
              <div className="rounded-md bg-muted p-4">
                <pre className="whitespace-pre-wrap font-mono text-sm">
                  {content?.content || "No content available"}
                </pre>
              </div>
            )}
            {!isContentEditable && (
              <p className="mt-2 text-sm text-muted-foreground">
                Content is read-only for imported skills.
              </p>
            )}
          </CardContent>
        </Card>

        {/* Files Section (if applicable) */}
        {files.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Files</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {files.map((file) => (
                  <div
                    key={file.path}
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <div className="flex items-center gap-2">
                      <File className="h-4 w-4 text-muted-foreground" />
                      <span className="font-mono text-sm">{file.path}</span>
                    </div>
                    <span className="text-sm text-muted-foreground">
                      {(file.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </ContentBlock>
  );
}

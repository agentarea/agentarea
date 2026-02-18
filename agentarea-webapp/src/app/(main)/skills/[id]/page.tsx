"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import {
  FileCode,
  Github,
  Upload,
  Trash2,
  Save,
  Loader2,
  ExternalLink,
  File,
  Pencil,
  Eye,
} from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  FileTree,
  FileTreeFile,
  FileTreeFolder,
} from "@/components/ai-elements/file-tree";
import { Streamdown } from "streamdown";
import {
  getSkill,
  getSkillContent,
  getSkillFiles,
  getSkillFile,
  updateSkill,
  deleteSkill,
  type Skill,
  type SkillContent,
  type SkillFile,
} from "@/lib/browser-api";
import { useToast } from "@/hooks/use-toast";
import YAML from "js-yaml";

interface FileNode {
  name: string;
  path: string;
  type: "file" | "folder";
  children: FileNode[];
  size?: number;
}

// Parse YAML frontmatter from markdown
function parseFrontmatter(content: string): { frontmatter: Record<string, unknown>; body: string; rawFrontmatter: string } {
  let body = content;
  let rawFrontmatter = "";
  let frontmatter: Record<string, unknown> = {};

  const match = content.match(/^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$/);
  if (match) {
    rawFrontmatter = match[1];
    body = match[2];
    try {
      frontmatter = YAML.load(rawFrontmatter) as Record<string, unknown> || {};
    } catch {
      frontmatter = {};
    }
  }

  return { frontmatter, body, rawFrontmatter };
}

function buildFileTree(files: SkillFile[], skillContent?: SkillContent | null): FileNode[] {
  const root: FileNode[] = [];
  const nodeMap = new Map<string, FileNode>();
  const hasSkillMd = files.some(f => f.path === "SKILL.md" || f.path.endsWith("/SKILL.md"));

  // Add SKILL.md only if not in files list
  if (skillContent?.content && !hasSkillMd) {
    root.push({
      name: "SKILL.md",
      path: "SKILL.md",
      type: "file",
      children: [],
      size: skillContent.content.length,
    });
  }

  const sortedFiles = [...files].sort((a, b) => a.path.localeCompare(b.path));

  for (const file of sortedFiles) {
    const parts = file.path.split("/");
    let currentPath = "";
    let currentLevel = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isLast = i === parts.length - 1;
      currentPath = currentPath ? `${currentPath}/${part}` : part;

      let node = nodeMap.get(currentPath);

      if (!node) {
        node = {
          name: part,
          path: currentPath,
          type: isLast ? "file" : "folder",
          children: [],
          ...(isLast && { size: file.size }),
        };
        nodeMap.set(currentPath, node);
        currentLevel.push(node);
      }

      if (!isLast) {
        currentLevel = node.children;
      }
    }
  }

  const sortNodes = (nodes: FileNode[]) => {
    nodes.sort((a, b) => {
      if (a.type === b.type) {
        return a.name.localeCompare(b.name);
      }
      return a.type === "folder" ? -1 : 1;
    });
    nodes.forEach((node) => {
      if (node.children.length > 0) {
        sortNodes(node.children);
      }
    });
  };

  sortNodes(root);
  return root;
}

function getSourceIcon(sourceType: string) {
  switch (sourceType) {
    case "github":
      return <Github className="h-4 w-4" />;
    case "zip":
      return <Upload className="h-4 w-4" />;
    default:
      return <FileCode className="h-4 w-4" />;
  }
}

function getSourceLabel(sourceType: string, tSource: (key: string) => string) {
  switch (sourceType) {
    case "github":
      return tSource("github");
    case "zip":
      return tSource("uploaded");
    default:
      return tSource("content");
  }
}

export default function SkillDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { toast } = useToast();
  const t = useTranslations("SkillsPage");
  const tDetail = useTranslations("SkillsPage.detail");
  const tSource = useTranslations("SkillsPage.source");
  const skillId = params.id as string;

  const [skill, setSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<SkillContent | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editContent, setEditContent] = useState("");
  const [hasChanges, setHasChanges] = useState(false);

  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

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
            title: t("error.loadSkills"),
            description: t("error.skillNotFound"),
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

        setEditName(skillData.name);
        setEditDescription(skillData.description || "");
        setEditContent(contentData?.content || "");

        if (contentData?.content) {
          setSelectedFile("SKILL.md");
          setFileContent(contentData.content);
        }
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

  const handleFileSelect = async (path: string) => {
    setSelectedFile(path);
    setLoadingFile(true);
    setIsEditing(false);

    try {
      if (path === "SKILL.md") {
        setFileContent(editContent || content?.content || "");
      } else {
        const { data, error } = await getSkillFile(skillId, path);
        if (error) {
          toast({
            title: t("error.loadSkills"),
            description: t("error.loadFileContent"),
            variant: "destructive",
          });
          setFileContent(null);
        } else {
          const fileData = data as { url?: string };
          if (fileData?.url) {
            const response = await fetch(fileData.url);
            const text = await response.text();
            setFileContent(text);
          } else {
            setFileContent(null);
          }
        }
      }
    } finally {
      setLoadingFile(false);
    }
  };

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
          title: t("error.loadSkills"),
          description: t("error.updateSkill"),
          variant: "destructive",
        });
        return;
      }

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

      toast({ title: t("success.skillUpdated"), description: t("success.skillUpdated") });
      setHasChanges(false);
      setIsEditing(false);
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
          title: t("error.loadSkills"),
          description: t("error.deleteSkill"),
          variant: "destructive",
        });
        return;
      }

      toast({ title: t("success.skillDeleted"), description: t("success.skillDeleted") });
      router.push("/skills");
    } finally {
      setDeleting(false);
    }
  };

  const renderFileTree = (nodes: FileNode[]): React.ReactNode => {
    return nodes.map((node) => {
      if (node.type === "folder") {
        return (
          <FileTreeFolder key={node.path} name={node.name} path={node.path}>
            {renderFileTree(node.children)}
          </FileTreeFolder>
        );
      }
      return (
        <FileTreeFile key={node.path} name={node.name} path={node.path}>
          <span className="size-4" />
          <File className="size-4 text-muted-foreground shrink-0" />
          <span className="truncate flex-1">{node.name}</span>
          {node.size !== undefined && (
            <span className="text-xs text-muted-foreground ml-2">
              {(node.size / 1024).toFixed(1)} KB
            </span>
          )}
        </FileTreeFile>
      );
    });
  };

  if (loading) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/skills" },
            { label: t("loading") },
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
  const fileTreeNodes = buildFileTree(files, content);
  const canEditFile = isContentEditable && selectedFile === "SKILL.md";

  // Parse frontmatter for display
  const parsed = fileContent ? parseFrontmatter(fileContent) : null;
  const hasFrontmatter = parsed && parsed.rawFrontmatter.length > 0;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/skills" },
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
              {tDetail("save")}
            </Button>
            <Button
              variant="destructive"
              size="xs"
              disabled={deleting}
              onClick={() => {
                if (window.confirm(t("confirm.deleteSkill", { skillName: skill.name }))) {
                  handleDelete();
                }
              }}
            >
              {deleting ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-2 h-4 w-4" />
              )}
              {tDetail("delete")}
            </Button>
          </div>
        ),
      }}
    >
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 p-6">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">{tDetail("details")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">{tDetail("name")}</Label>
                <Input
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="h-8 text-sm"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs text-muted-foreground">{tDetail("description")}</Label>
                <Input
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder={tDetail("description")}
                  className="h-8 text-sm"
                />
              </div>
              <div className="flex items-center gap-2 pt-1">
                <Badge variant="outline" className="gap-1 text-xs">
                  {getSourceIcon(skill.source_type)}
                  {getSourceLabel(skill.source_type, tSource)}
                </Badge>
                {skill.source_url && (
                  <a
                    href={skill.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
              <div className="text-xs text-muted-foreground pt-2 border-t">
                {tDetail("updated")} {formatDistanceToNow(new Date(skill.updated_at), { addSuffix: true })}
              </div>
            </CardContent>
          </Card>

          {fileTreeNodes.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">{tDetail("files")}</CardTitle>
              </CardHeader>
              <CardContent>
                <FileTree
                  defaultExpanded={new Set()}
                  selectedPath={selectedFile || undefined}
                  onSelect={(path) => void handleFileSelect(path)}
                >
                  {renderFileTree(fileTreeNodes)}
                </FileTree>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Content */}
        <div className="lg:col-span-3">
          <Card className="h-full">
            <CardHeader className="border-b py-3 flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-mono">
                {selectedFile || tDetail("selectFile")}
              </CardTitle>
              {canEditFile && (
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => setIsEditing(!isEditing)}
                >
                  {isEditing ? (
                    <>
                      <Eye className="mr-1 h-3 w-3" /> {tDetail("view")}
                    </>
                  ) : (
                    <>
                      <Pencil className="mr-1 h-3 w-3" /> {tDetail("edit")}
                    </>
                  )}
                </Button>
              )}
            </CardHeader>
            <CardContent className="p-0">
              {loadingFile ? (
                <div className="flex h-96 items-center justify-center">
                  <LoadingSpinner />
                </div>
              ) : !selectedFile ? (
                <div className="flex h-96 items-center justify-center text-muted-foreground text-sm">
                  {tDetail("selectFile")}
                </div>
              ) : !fileContent ? (
                <div className="flex h-96 items-center justify-center text-muted-foreground text-sm">
                  {tDetail("emptyFile")}
                </div>
              ) : isEditing && canEditFile ? (
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="w-full h-[600px] p-4 bg-background text-sm font-mono resize-none focus:outline-none"
                  spellCheck={false}
                />
              ) : (
                <div className="p-6 space-y-4">
                  {/* Frontmatter card */}
                  {hasFrontmatter && (
                    <div className="rounded-lg border bg-card overflow-hidden">
                      <div className="bg-muted px-4 py-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b">
                        {tDetail("skillConfiguration")}
                      </div>
                      <div className="p-4">
                        <pre className="text-sm font-mono whitespace-pre-wrap text-foreground">{parsed!.rawFrontmatter}</pre>
                      </div>
                    </div>
                  )}
                  
                  {/* Content */}
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    <Streamdown>{parsed?.body || fileContent}</Streamdown>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </ContentBlock>
  );
}

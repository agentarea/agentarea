"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useParams, useRouter } from "next/navigation";
import { Loader2, Save, Eye, Pencil, FileText, FileX } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Streamdown } from "streamdown";
import DeleteButton from "@/components/DeleteButton";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import SkillPanel from "@/components/SkillPanel/SkillPanel";
import Section from "@/components/TaskInfoPanel/components/Section";
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
import { AnimatedTabs } from "@/components/ui/animated-tabs";

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

export default function SkillDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { toast } = useToast();
  const t = useTranslations("SkillsPage");
  const tDetail = useTranslations("SkillsPage.detail");
  const skillId = params.id as string;

  const [skill, setSkill] = useState<Skill | null>(null);
  const [content, setContent] = useState<SkillContent | null>(null);
  const [files, setFiles] = useState<SkillFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

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
  }, [skillId, router, toast, t]);

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

  if (loading) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("title"), href: "/skills" },
            { label: skillId },
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
  const canEditFile = isContentEditable && selectedFile === "SKILL.md";
  const editModeTab = isEditing ? "edit" : "view";

  // Parse frontmatter for display
  const parsed = fileContent ? parseFrontmatter(fileContent) : null;
  const hasFrontmatter = parsed && parsed.rawFrontmatter.length > 0;

  return (
    <ContentBlock
      className="p-0 overflow-hidden"
      header={{
        breadcrumb: [
          { label: t("title"), href: "/skills" },
          { label: skill.name },
        ],
        controls: (
          <div className="flex items-center gap-2">
            <DeleteButton
              size="xs"
              itemId={skillId}
              itemName={skill.name}
              onDelete={deleteSkill}
              redirectPath="/skills"
              title={t("confirm.deleteSkillTitle") || tDetail("delete")}
              description={t("confirm.deleteSkill", { skillName: skill.name })}
              successMessage={t("success.skillDeleted")}
            />
          </div>
        ),
      }}
    >
      <div className="flex h-full w-full overflow-hidden">
        {/* Main Content Area */}
        <div className="flex-1 overflow-auto p-4 md:p-6">
          <div className="h-full max-w-4xl mx-auto">
            <Card className="h-full flex flex-col overflow-hidden p-0 cursor-default hover:shadow-none">
              <CardHeader className="border-b border-border/70 bg-sidebar p-3 flex flex-row items-center justify-between shrink-0 space-y-0">
                <CardTitle className="text-xs font-mono">
                  {selectedFile || tDetail("selectFile")}
                </CardTitle>
              <div className="flex items-center gap-2">
                {hasChanges && (
                  <Button
                    variant="outline"
                    size="xs"
                    className="border-border/70 bg-background/60 shadow-none hover:bg-muted/70"
                    onClick={handleSave}
                    disabled={saving}
                  >
                    {saving ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="mr-2 h-4 w-4" />
                    )}
                    {tDetail("save")}
                  </Button>
                )}

                {canEditFile && (
                  <AnimatedTabs
                    layoutId="skill-edit-toggle"
                    tabs={[
                      {
                        value: "view",
                        label: tDetail("view"),
                        icon: <Eye className="h-3.5 w-3.5" />,
                      },
                      {
                        value: "edit",
                        label: tDetail("edit"),
                        icon: <Pencil className="h-3.5 w-3.5" />,
                      },
                    ]}
                    activeTab={editModeTab}
                    onChange={(val) => setIsEditing(val === "edit")}
                    className="w-auto rounded-md border border-border/70 bg-background/60 p-0.5 text-xs font-normal"
                    tabClassName="flex-none px-2 py-1 gap-1"
                    labelClassName="sr-only"
                    activeIndicatorClassName="bg-background shadow-none ring-1 ring-border/70"
                    hoverIndicatorClassName="bg-muted/60"
                  />
                )}
              </div>
              </CardHeader>
              <CardContent className="p-0 flex-1 overflow-auto relative">
                {loadingFile ? (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <LoadingSpinner />
                  </div>
                ) : !selectedFile ? (
                  <div className="absolute inset-0 flex items-center justify-center p-6">
                    <EmptyState
                      className="max-w-none w-full border border-border/70 p-8 hover:bg-muted/30"
                      title={tDetail("selectFile")}
                      description=""
                      icons={[FileText]}
                    />
                  </div>
                ) : !fileContent ? (
                  <div className="absolute inset-0 flex items-center justify-center p-6">
                    <EmptyState
                      className="max-w-none w-full border border-border/70 p-8 hover:bg-muted/30"
                      title={tDetail("emptyFile")}
                      description=""
                      icons={[FileX]}
                    />
                  </div>
                ) : isEditing && canEditFile ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full h-full p-4 bg-background text-sm font-mono leading-relaxed resize-none focus:outline-none"
                    spellCheck={false}
                  />
                ) : (
                  <div className="p-4 space-y-4">
                    {hasFrontmatter && (
                      <Section
                        title={tDetail("skillConfiguration")}
                        className="shadow-none"
                        contentClassName="p-4"
                      >
                        <pre className="text-xs font-mono whitespace-pre-wrap text-foreground">
                          {parsed!.rawFrontmatter}
                        </pre>
                      </Section>
                    )}

                    <div className="prose prose-sm dark:prose-invert max-w-none pb-10 prose-headings:font-semibold prose-headings:tracking-tight prose-h1:text-xl prose-h1:mt-6 prose-h1:mb-2 prose-h2:text-lg prose-h2:mt-5 prose-h2:mb-2 prose-h3:text-base prose-h3:mt-4 prose-h3:mb-1.5 prose-p:leading-relaxed prose-ul:my-3 prose-ol:my-3 prose-li:my-1 prose-pre:bg-muted prose-pre:border prose-pre:border-border/70 prose-pre:rounded-md prose-pre:p-4 prose-code:bg-muted prose-code:px-1 prose-code:py-0.5 prose-code:rounded">
                      <Streamdown>{parsed?.body || fileContent}</Streamdown>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Right Sidebar Dock */}
        <TaskInfoPanelDock
          storageKey="skill-info-panel"
          panel={
            <SkillPanel
              skill={skill}
              files={files}
              onFileSelect={handleFileSelect}
              selectedFile={selectedFile}
            />
          }
        />
      </div>
    </ContentBlock>
  );
}
